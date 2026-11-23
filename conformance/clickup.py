"""ClickUp's side of the suite: building the adapter, checking a Space is
ready, and the sprint case that stands in for the three generic ones.

Nothing in a ClickUp Space is provisioned here. Task types are workspace
settings, statuses and the sprint Folder are the Space's own, and a custom
field cannot be made through the API. So `provision` reads the board and,
when the config does not fit, stops for the operator with what to change.

**Sprints.** ClickUp's API cannot make a sprint or close one, so the
generic `iterations`, `close` and `rollover` cases cannot run. `sprints`
takes their place: it moves this run's items into the sprints the Space
already has and checks what the adapter refuses.

**The one DELETE.** Clearing a label takes a tag off a task with a DELETE,
the only one the transport sends. The wire log this harness hands the suite
counts it under its own name, so the `no-delete` case still fails on any
other.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from adapters.base import Unsupported, ValidationError
from adapters.clickup.adapter import ClickUpAdapter
from adapters.clickup.transport import API, DEFAULT_THROTTLE, UNTAG, ClickUpTransport
from conformance.cases import Case, Context, Failed, NeedsOperator, Skipped, _listed, expect
from server import secrets
from server.config import BoardConfig
from server.model import Iteration, IterationState

TAG_OFF = "DELETE (a tag off a task)"  # how the one allowed DELETE is counted
REPLACED = ("iterations", "close", "rollover")  # the generic cases a ClickUp sprint cannot run


def wire(log: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The transport's log, with a tag coming off a task under its own name."""
    return [(TAG_OFF if method == "DELETE" and UNTAG.match(path) else method, path) for method, path in log]


def make_adapter(
    config: BoardConfig, *, throttle: float = DEFAULT_THROTTLE, today: Callable[[], date] | None = None,
) -> tuple[ClickUpAdapter, Callable[[], list[tuple[str, str]]]]:
    """The adapter on a real transport, plus that transport's wire log.
    `today` is unused: a sprint's state comes from its instants, on the adapter's own clock."""
    conn = config.connection
    transport = ClickUpTransport(lambda: secrets.get(conn.token_env), base_url=conn.base_url or API, throttle=throttle)
    return ClickUpAdapter(config, transport), lambda: wire(transport.log)


def provision(ctx: Context) -> None:
    a = ctx.adapter
    assert isinstance(a, ClickUpAdapter)
    board = a.describe_board()
    if board.problems:
        raise NeedsOperator(
            "the Space does not fit the config; fix it in ClickUp (task types, statuses, tags, the sprint Folder, "
            "the idempotency field) or in the config, then re-run: " + "; ".join(board.problems)
        )
    ctx.note(f"Space {board.project_name!r}: nothing to create (types are workspace settings; statuses, tags and "
             "the sprint Folder are the Space's own; a custom field is made in ClickUp)")
    ctx.note(f"{len(board.containers)} List(s) outside the sprint Folder, {len(board.iterations)} sprint(s), "
             f"{len(board.members)} member(s); time zone {board.features.get('time_zone')}")


def sprints(ctx: Context) -> None:
    """The Space's own sprints: this run's items join the active one and a
    planned one, a sprint is found by name and never made, and none is closed
    from here."""
    a = ctx.adapter
    known = [a.get_iteration(i.id) for i in a.describe_board().iterations]
    active = next((s for s in known if s.state is IterationState.ACTIVE), None)
    planned = next((s for s in known if s.state is IterationState.PLANNED), None)
    closed = next((s for s in known if s.state is IterationState.CLOSED), None)
    if active is None:
        raise Skipped("the sprint Folder has no active sprint, and ClickUp's API cannot make one; "
                      "re-run once a sprint covers today")
    ctx.ids["iteration_current"] = active.id or ""

    a.move_to_iteration([ctx.ids["story"], ctx.ids["task"]], active.id or active.name)
    if planned is not None:
        a.move_to_iteration([ctx.ids["bug"]], planned.name)  # by name this time
        ctx.ids["iteration_next"] = planned.id or ""
    board = _listed(ctx)
    wanted = [("story", active), ("task", active)] + ([("bug", planned)] if planned else [])
    for key, want in wanted:
        got = board[ctx.ids[key]].iteration
        expect(got == want.id, f"the {key} reads iteration {got!r}, expected {want.name} ({want.id})")
    held = {i.id for i in a.find_items(iteration=active.id, limit=500)}
    expect({ctx.ids["story"], ctx.ids["task"]} <= held, f"find_items(iteration={active.name!r}) misses the items just added")
    ctx.note(f"story + task added to {active.name} (active)"
             + (f", bug to {planned.name} (planned)" if planned else "; no planned sprint to add the bug to")
             + "; the list read and the sprint's own read agree")

    again = a.create_iteration(Iteration(active.name, start=active.start, end=active.end))
    expect(again.id == active.id, f"create_iteration({active.name!r}) returned {again.id}, not the existing {active.id}")
    ctx.note(f"create_iteration({active.name!r}) found the existing sprint: no duplicate")
    for what, call in (("make a sprint", lambda: a.create_iteration(Iteration(f"Conformance {ctx.run_id} No Such Sprint"))),
                       ("close an open sprint", lambda: a.close_iteration(active.id or active.name))):
        before = len(ctx.calls())
        try:
            call()
        except Unsupported as exc:
            sent = [m for m, _ in ctx.calls()[before:] if m != "GET"]
            expect(not sent, f"the refusal to {what} still sent {sent}")
            ctx.note(f"asked to {what}, the adapter refuses and writes nothing: {exc}")
        else:
            raise Failed(f"the adapter did not refuse to {what}")
    if closed is None:
        ctx.note("no closed sprint in the Folder yet, so its refusal of new items was not exercised")
        return
    try:
        a.move_to_iteration([ctx.ids["epic"]], closed.id or closed.name)
    except ValidationError as exc:
        ctx.note(f"a closed sprint refuses new items, mapped to ValidationError: {exc}")
    else:
        raise Failed(f"closed sprint {closed.name} accepted a new item")


def cases(generic: tuple[Case, ...]) -> tuple[Case, ...]:
    """The generic cases with `sprints` in place of the three ClickUp cannot run."""
    kept = [c for c in generic if c.name not in REPLACED]
    at = next(n for n, c in enumerate(generic) if c.name == REPLACED[0])
    kept.insert(at, Case("sprints", "this run's items join the Space's own sprints; none is made or closed from here", sprints))
    return tuple(kept)
