"""Operator entry: run the conformance suite against a throwaway board.

  uv run python -m conformance boards/<board>.toml --dry-run   # list; no calls
  uv run python -m conformance boards/<board>.toml             # live — real writes

A live run writes to the board the config names (items, a feature, two
iterations, labels, types) and never deletes. Point it only at a
throwaway project. Exit codes: 0 pass, 1 a case failed, 2 bad config or
backend, 3 stopped — act on the last note (or wait out a 429 / the edge
wall), then re-run with the same run id to resume.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from adapters.plane.transport import DEFAULT_THROTTLE
from conformance import plane, runner
from conformance.cases import Context
from server.config import InvalidBoardConfig, load

REPORTS = Path(__file__).resolve().parent / "reports"
HARNESSES = {"plane": plane.make_adapter}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m conformance", description=__doc__.split("\n\n")[0])
    parser.add_argument("config", help="path to the throwaway board's TOML config")
    parser.add_argument("--dry-run", action="store_true", help="list the cases and what the record shows; no calls")
    parser.add_argument("--run-id", help="names this run's items and record (default: today, YYYYMMDD)")
    parser.add_argument("--throttle", type=float, default=DEFAULT_THROTTLE, help="seconds between calls")
    parser.add_argument("--reports", type=Path, default=REPORTS, help="where run records go")
    args = parser.parse_args(argv)

    try:
        cfg = load(args.config)
    except InvalidBoardConfig as exc:
        print("invalid board config:\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    today = date.today()
    run_id = args.run_id or f"{today:%Y%m%d}"
    record = args.reports / f"{Path(args.config).stem}-{run_id}.json"
    state = runner.load_state(record, run_id)
    cases = runner.cases_for(cfg.backend.value)
    where = " / ".join(f"{k}={v}" for k, v in cfg.connection.ids.items())
    print(f"conformance: {cfg.backend.value} {where}, run {run_id}\nrecord: {record}")

    if args.dry_run:
        for case in cases:
            rec = state["cases"].get(case.name)
            mark = f"[{rec['status']} {rec['at']}]" if rec else "[not run]"
            print(f"  {case.name:<11} {mark:<30} {case.summary}")
        return 0

    harness = HARNESSES.get(cfg.backend.value)
    if harness is None:
        print(f"no conformance harness for backend {cfg.backend.value!r}", file=sys.stderr)
        return 2
    adapter, calls = harness(cfg, throttle=args.throttle)
    ctx = Context(adapter, cfg, run_id, today, calls)
    verdict = runner.run(cases, ctx, state, save=lambda s: runner.save_state(record, s))
    statuses = [c["status"] for c in state["cases"].values()]
    print(f"\nverdict: {verdict.upper()} — " + ", ".join(f"{statuses.count(s)} {s}" for s in (runner.PASS, runner.SKIP, runner.FAIL, runner.STOP) if s in statuses))
    return {runner.PASS: 0, runner.FAIL: 1, runner.STOP: 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
