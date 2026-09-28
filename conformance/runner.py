"""Run the cases in order, record every outcome, resume from the record.

The record (`conformance/reports/<board>-<run id>.json`, gitignored — it
holds board content) keeps each case's status, notes and call counts, the
ids later cases need, and the run's cumulative wire totals. A re-run with
the same run id skips what already passed and picks up at the first case
that did not — so a 429 or the Cloudflare wall costs a wait, not a redo.
A case marked `always` (no-delete) runs on every process regardless, so a
case added to a finished run is covered too.

The run stops at the first case that fails or needs the operator: later
cases build on earlier ones.
"""

from __future__ import annotations

import json
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from adapters.base import AdapterError, Blocked, RateLimited
from conformance.cases import GENERIC_CASES, Case, Context, Failed, NeedsOperator, Skipped
from server.model import InvalidWorkItem

PASS, SKIP, FAIL, STOP = "pass", "skip", "fail", "stop"


def cases_for(backend: str) -> tuple[Case, ...]:
    from conformance import jira, plane

    provisioner = {"plane": plane.provision, "jira": jira.provision}.get(backend)

    def provision(ctx: Context) -> None:
        if provisioner is None:
            raise Skipped(f"no provisioner for {backend}; provision the board by hand")
        provisioner(ctx)

    return (
        Case("provision", "turn on the features, create the types and labels the config names (idempotent)", provision),
        *GENERIC_CASES,
    )


def load_state(path: Path, run_id: str) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {"run_id": run_id, "cases": {}, "ids": {}, "wire": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(path)


def _calls_text(calls: dict[str, int]) -> str:
    return " · ".join(f"{m} {n}" for m, n in sorted(calls.items())) or "no calls"


def run(
    cases: tuple[Case, ...],
    ctx: Context,
    state: dict[str, Any],
    save: Callable[[dict[str, Any]], None],
    echo: Callable[[str], None] = print,
) -> str:
    """Run what the record does not already show as passed; return the
    verdict — PASS (skips allowed), FAIL, or STOP (re-run after acting)."""
    recorded: dict[str, Any] = state.setdefault("cases", {})
    ctx.ids = state.setdefault("ids", {})
    ctx.wire_before = Counter(state.get("wire") or {})
    for case in cases:
        prior = recorded.get(case.name)
        if prior and prior["status"] in (PASS, SKIP) and not case.always:
            echo(f"  {prior['status'].upper():<4}  {case.name:<11} recorded {prior['at']}")
            continue
        ctx.notes = []
        before = len(ctx.calls())
        status, crash = PASS, None
        try:
            case.run(ctx)
        except Skipped as exc:
            status = SKIP
            ctx.note(f"skipped: {exc}")
        except NeedsOperator as exc:
            status = STOP
            ctx.note(f"needs the operator: {exc}")
        except (RateLimited, Blocked) as exc:
            status = STOP
            ctx.note(f"{exc.__class__.__name__}: {exc} — wait, then re-run to resume")
        except Failed as exc:
            status = FAIL
            ctx.note(f"failed: {exc}")
        except (AdapterError, InvalidWorkItem) as exc:
            status = FAIL
            detail = getattr(exc, "detail", None)
            ctx.note(f"{exc.__class__.__name__}: {exc}" + (f" — {detail}" if detail else ""))
        except Exception as exc:  # a bug in the suite or the adapter: record it, then surface it
            status, crash = FAIL, exc
            ctx.note(f"crashed: {exc!r}")
        spent = Counter(m for m, _ in ctx.calls()[before:])
        recorded[case.name] = {
            "status": status,
            "at": datetime.now().isoformat(timespec="seconds"),
            "notes": list(ctx.notes),
            "calls": dict(spent),
        }
        state["wire"] = dict(ctx.wire_before + Counter(m for m, _ in ctx.calls()))
        save(state)
        echo(f"  {status.upper():<4}  {case.name:<11} {_calls_text(dict(spent))}")
        for n in ctx.notes:
            echo(f"        - {n}")
        if crash is not None:
            echo("".join(traceback.format_exception(crash)))
        if status in (FAIL, STOP):
            return status
    return PASS
