"""Plane's side of the suite: building the adapter, and provisioning a fresh
throwaway project so the generic cases can run.

A fresh Plane project has Work Item Types and Epics off, no types, no
labels (the 2026-09-22 read of AGADMIN). Provisioning turns the features
on, creates the non-epic types and the labels the config names, and
stops for the operator where the API cannot help: whether `PATCH
…/features` flips `epics` is one of the questions this case answers.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Callable

from adapters.base import NotFound, ValidationError
from adapters.plane.adapter import PlaneAdapter
from adapters.plane.transport import DEFAULT_THROTTLE, PlaneTransport
from conformance.cases import Context, NeedsOperator, expect
from server import secrets
from server.config import BoardConfig
from server.model import Level, Materialization

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def make_adapter(
    config: BoardConfig, *, throttle: float = DEFAULT_THROTTLE, today: Callable[[], date] = date.today,
) -> tuple[PlaneAdapter, Callable[[], list[tuple[str, str]]]]:
    """The adapter on a real transport, plus that transport's wire log."""
    conn = config.connection
    transport = PlaneTransport(lambda: secrets.get(conn.token_env), base_url=conn.base_url, throttle=throttle)
    return PlaneAdapter(config, transport, today=today), lambda: transport.log


def wanted_features(config: BoardConfig) -> list[str]:
    hows = {m.how for m in config.levels.values()}
    wanted = []
    if Materialization.TYPE in hows:
        wanted.append("work_item_types")
    if config.levels[Level.EPIC].how is Materialization.TYPE:
        wanted.append("epics")
    if Materialization.CONTAINER in hows:
        wanted.append("modules")
    wanted.append("cycles")  # iterations
    return wanted


def provision(ctx: Context) -> None:
    a = ctx.adapter
    assert isinstance(a, PlaneAdapter)
    cfg = ctx.config
    board = a.describe_board()
    off = [f for f in wanted_features(cfg) if board.features.get(f) is not True]
    if off:
        try:
            after = a.set_features(**{f: True for f in off})
        except (ValidationError, NotFound) as exc:  # Plane refused the flip; anything else is a real failure
            ctx.note(f"PATCH …/features {off} refused: {exc.__class__.__name__}: {exc}")
            after = {}
        flipped = [f for f in off if after.get(f) is True]
        still = [f for f in off if f not in flipped]
        if flipped:
            ctx.note(f"PATCH …/features turned on {', '.join(flipped)} — the API can flip them")
        if still:
            ctx.note(f"PATCH …/features left off: {', '.join(still)}")
            raise NeedsOperator(
                f"turn on {', '.join(still)} in Plane → {board.project_name} → Project Settings → Features, then re-run"
            )
        board = a.describe_board()
    else:
        ctx.note(f"features already on: {', '.join(wanted_features(cfg))}")

    epic = cfg.levels[Level.EPIC]
    if epic.how is Materialization.TYPE:
        hit = next((t for t in board.types if (epic.ref or "").lower() in (t.id, t.name.lower())), None)
        if hit is None:
            have = ", ".join(t.name for t in board.types) or "(none)"
            raise NeedsOperator(
                f"no epic type {epic.ref!r} on the board (types: {have}); the API cannot create one — "
                "toggle Epics off and on in Project Settings → Features, then re-run"
            )
        ctx.note(f"epic type {hit.name!r} present (is_epic={hit.is_epic})")

    types = [
        m.ref for lv, m in cfg.levels.items()
        if m.how is Materialization.TYPE and lv is not Level.EPIC and m.ref and not _UUID.match(m.ref)
    ]
    labels = [cfg.labels.review, *cfg.labels.taxonomy,
              *(m.ref for m in cfg.levels.values() if m.how in (Materialization.PARENT, Materialization.LABEL) and m.ref)]
    had_types = {t.name.lower() for t in board.types}
    had_labels = {l.name.lower() for l in board.labels}
    board = a.provision(types=types, labels=labels)
    made_types = sorted({t for t in types if t.lower() not in had_types})
    made_labels = sorted({l for l in labels if l.lower() not in had_labels})
    ctx.note(f"work-item types created: {', '.join(made_types) or 'none'}; board types now {', '.join(t.name for t in board.types)}")
    ctx.note(f"labels created via POST …/labels/: {', '.join(made_labels) or 'none'}")
    expect(not board.problems, "the board still does not fit after provisioning: " + "; ".join(board.problems))
