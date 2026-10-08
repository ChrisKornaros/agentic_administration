"""The conformance cases — backend-agnostic, written against `adapters.base`.

Each case is a function of a `Context`. It raises `Failed` when the adapter
breaks its contract, `NeedsOperator` when a human must act before a re-run,
and `Skipped` when it cannot run on this board; anything else is a pass.
Cases record what they saw with `ctx.note` — the notes are the evidence.

Every case is safe to re-run: items are found by `external_id` (namespaced
by the run id) before they are created, features by name, iterations by
name. Ids later cases need go in `ctx.ids`, which the runner persists, so
a run cut short by a 429 or the Cloudflare wall resumes where it stopped.

The provisioning case is backend-specific (a fresh board lacks the types
and labels the config names) and lives with its backend, e.g.
`conformance.plane.provision`.
"""

from __future__ import annotations

import calendar
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from adapters.base import Adapter, FieldInfo, FieldKind, ItemPatch, NotFound, ValidationError
from server.config import BoardConfig, Naming
from server.model import (
    CollapseRule,
    CollapseTarget,
    Comment,
    InvalidWorkItem,
    ItemRef,
    Iteration,
    IterationState,
    Level,
    Materialization,
    State,
    WorkItem,
)


class Failed(AssertionError):
    """The adapter did not do what the interface promises."""


class NeedsOperator(Exception):
    """A human must act (e.g. flip a UI-only toggle); then re-run."""


class Skipped(Exception):
    """The case cannot run on this board or in this run; the reason is kept."""


def expect(condition: object, message: str) -> None:
    if not condition:
        raise Failed(message)


@dataclass
class Context:
    adapter: Adapter
    config: BoardConfig
    run_id: str
    today: date
    calls: Callable[[], list[tuple[str, str]]]  # (method, path) sent by this process
    ids: dict[str, str] = field(default_factory=dict)  # persisted across resumes
    wire_before: Counter = field(default_factory=Counter)  # methods sent by earlier processes of this run
    notes: list[str] = field(default_factory=list)  # the current case's evidence

    def note(self, text: str) -> None:
        self.notes.append(text)

    def xid(self, name: str) -> str:
        """The external_id for this run's item `name`."""
        return f"conformance:{self.run_id}:{name}"


@dataclass(frozen=True)
class Case:
    name: str
    summary: str
    run: Callable[[Context], None]
    always: bool = False  # re-run on every process, even when the record shows it passed


# --- helpers -----------------------------------------------------------------------


def find_or_create(ctx: Context, item: WorkItem) -> WorkItem:
    """Idempotent create keyed on `item.external_id`."""
    hits = ctx.adapter.find_items(external_id=item.external_id)
    expect(len(hits) <= 1, f"{len(hits)} items carry external_id {item.external_id!r}")
    if hits:
        ctx.note(f"reused {hits[0].key or hits[0].id} ({item.external_id}) from an earlier attempt")
        return hits[0]
    return ctx.adapter.create_item(item)


def iteration_name(naming: Naming, day: date) -> str:
    return naming.iteration.replace("YYYY", f"{day:%Y}").replace("MM", f"{day:%m}").replace("DD", f"{day:%d}")


def _find_or_create_iteration(ctx: Context, it: Iteration) -> tuple[Iteration, bool]:
    try:
        return ctx.adapter.get_iteration(it.name), False
    except NotFound:
        created = ctx.adapter.create_iteration(it)
        return ctx.adapter.get_iteration(created.id or it.name), True


def _listed(ctx: Context) -> dict[str, WorkItem]:
    """The board's list read — where membership (feature, iteration) shows."""
    return {i.id: i for i in ctx.adapter.find_items(limit=10_000) if i.id}


def _label_in(name: str, labels: tuple[str, ...]) -> bool:
    return name.lower() in (l.lower() for l in labels)


def _carries(item: WorkItem, rule: CollapseRule | None, level: Level, ref: ItemRef) -> bool:
    """Whether `item` carries a collapsed attachment where its rule puts it.
    Spaces and dashes compare equal: a tracker's labels may hold no spaces."""
    if rule is None:
        return False
    text = rule.template.format(level=level.value, name=ref.key or ref.id, id=ref.id, key=ref.key or "")

    def squash(s: str) -> str:
        return re.sub(r"[\s-]+", "-", s.strip().lower())

    if rule.target is CollapseTarget.LABEL:
        return any(squash(l) == squash(text) for l in item.labels)
    if rule.target is CollapseTarget.COMPONENT:
        return item.component is not None and squash(item.component) == squash(text)
    return text in item.description


# --- the cases ---------------------------------------------------------------------


def describe(ctx: Context) -> None:
    board = ctx.adapter.describe_board()
    ctx.note(
        f"{board.backend} project {board.project_key or board.project_id}: {len(board.types)} types, "
        f"{len(board.states)} states, {len(board.labels)} labels, {len(board.members)} members, "
        f"{len(board.containers)} containers, {len(board.iterations)} iterations"
    )
    expect(not board.problems, "config does not fit the board: " + "; ".join(board.problems))
    unresolved = sorted(
        lv.value for lv, how in ctx.adapter.capabilities.levels.items()
        if how is not Materialization.NONE and lv not in board.resolved
    )
    expect(not unresolved, f"materialized levels the board did not resolve: {', '.join(unresolved)}")
    ctx.note("config fits the board; every materialized level resolved — writes are open")


def epic_round_trip(ctx: Context) -> None:
    a = ctx.adapter
    xid = ctx.xid("epic")
    epic = find_or_create(ctx, WorkItem(
        Level.EPIC, "Conformance Epic",
        description=f"Filed by the **conformance suite**, run `{ctx.run_id}`.\n\n- external_id round-trip\n- nothing is ever deleted",
        external_id=xid,
    ))
    expect(epic.id and epic.level is Level.EPIC, f"create returned {epic.level.value} {epic.id!r}, not an epic with an id")

    before = len(ctx.calls())
    hits = a.find_items(external_id=xid)
    spent = len(ctx.calls()) - before
    expect([h.id for h in hits] == [epic.id],
           f"find_items(external_id={xid!r}) returned {[h.key or h.id for h in hits]}, expected exactly {epic.key}")
    ctx.note(f"external_id round-trip: {epic.key} written with {xid!r}; find_items(external_id=…) finds exactly it in {spent} call{"" if spent == 1 else "s"}")
    expect(a.find_items(external_id=ctx.xid("absent")) == [], "an external_id nobody wrote matched an item")

    by_key = a.get_item(epic.key) if epic.key else a.get_item(epic.id)
    expect(by_key.id == epic.id, f"get_item({epic.key!r}) returned {by_key.id}, not {epic.id}")
    expect(by_key.external_id == xid, f"the read-back external_id is {by_key.external_id!r}")
    expect("conformance suite" in by_key.description, f"the Markdown description did not survive: {by_key.description!r}")
    ctx.note(f"get_item by key and by id agree; the Markdown description reads back as {by_key.description[:48]!r}…")
    ctx.ids["epic"] = epic.id


def placement(ctx: Context) -> None:
    a = ctx.adapter
    epic = ItemRef(ctx.ids["epic"], Level.EPIC)
    review = ctx.config.labels.review

    feature_name = f"Conformance {ctx.run_id}"
    feature: WorkItem | None = None
    if a.capabilities.materializes(Level.FEATURE):
        feature = next((f for f in a.find_items(feature_name, level=Level.FEATURE) if f.title == feature_name), None)
        if feature is None:
            feature = a.create_item(WorkItem(Level.FEATURE, feature_name, description="The conformance suite's feature."))
        else:
            ctx.note(f"reused feature {feature_name!r} from an earlier attempt")
        feature_ref = ItemRef(feature.id or "", Level.FEATURE)
    else:  # collapsed: the name is the reference, as the MCP server passes it
        feature_ref = ItemRef(feature_name, Level.FEATURE)

    story = find_or_create(ctx, WorkItem(
        Level.STORY, "Requester Files A Story", parent=epic, feature=feature_ref, labels=(review,),
        description="As a requester I can file a story.\n\n**Acceptance:** it lands under the epic, in the feature, flagged for review.",
        external_id=ctx.xid("story"),
    ))
    bug = find_or_create(ctx, WorkItem(Level.BUG, "Requester Reports A Bug", parent=epic, external_id=ctx.xid("bug")))
    task = find_or_create(ctx, WorkItem(
        Level.TASK, "Write The Acceptance Test", parent=ItemRef(story.id or "", Level.STORY), external_id=ctx.xid("task"),
    ))

    # read back from the board's list — the read that carries membership
    board = _listed(ctx)
    for made in (story, bug, task):
        expect(made.id in board, f"{made.key} is missing from the board's item list")
    s, b, t = board[story.id], board[bug.id], board[task.id]
    expect(s.level is Level.STORY and s.parent and s.parent.id == epic.id, f"story {s.key} reads back as {s.level.value} under {s.parent}")
    expect(b.level is Level.BUG and b.parent and b.parent.id == epic.id, f"bug {b.key} reads back as {b.level.value} under {b.parent}")
    expect(t.level is Level.TASK and t.parent and t.parent.id == story.id, f"task {t.key} reads back as {t.level.value} under {t.parent}")
    expect(_label_in(review, s.labels), f"story {s.key} lacks the review label {review!r}: {s.labels}")
    if feature is not None:
        expect(s.feature is not None and s.feature.id == feature.id, f"story {s.key} is not in feature {feature_name!r} (reads {s.feature})")
    else:
        rule = ctx.config.levels[Level.FEATURE].collapse
        expect(_carries(s, rule, Level.FEATURE, feature_ref),
               f"story {s.key} does not carry feature {feature_name!r} by its collapse rule "
               f"({rule.target.value if rule else '?'}): labels {s.labels}")
    ctx.note(f"epic > story {s.key} (in feature {feature_name!r}, labelled {review!r}) > task {t.key}; bug {b.key} under the epic")
    if feature is None:
        ctx.note(f"the feature collapsed: the story carries it as {[l for l in s.labels if not _label_in(l, (review,))]}")

    if feature is not None:
        single = a.get_item(story.id or "")
        ctx.note("get_item alone " + ("also carries" if single.feature else "does NOT carry") + " feature membership; the list read does")

    n = len(ctx.calls())
    try:
        a.create_item(WorkItem(Level.TASK, "Misplaced Task", parent=epic))
    except InvalidWorkItem:
        pass
    else:
        raise Failed("the model let a task be parented under an epic it knew was an epic")
    expect(len(ctx.calls()) == n, "a model-invalid item reached the wire")
    ctx.note("a task under a known epic is refused by the model before any call")
    ctx.ids.update(feature=(feature.id or "") if feature else feature_name,
                   story=story.id or "", bug=bug.id or "", task=task.id or "")


def hierarchy_probe(ctx: Context) -> None:
    """A task straight under an epic, the epic's level unstated so only the
    tracker can object. Either answer is conformant — accepted (no hierarchy
    rules on the board) or a mapped `ValidationError`; the note says which."""
    item = WorkItem(
        Level.TASK, "Task Parented Straight Under The Epic",
        description="Hierarchy probe: which answer does the tracker give?",
        parent=ItemRef(ctx.ids["epic"]), external_id=ctx.xid("task-under-epic"),
    )
    try:
        made = find_or_create(ctx, item)
    except ValidationError as exc:
        ctx.note(f"the tracker refused a task under an epic (hierarchy rules on), mapped to ValidationError: {exc}")
        return
    ctx.note(f"the tracker accepted {made.key}, a task parented under an epic — no hierarchy rules; the model is the guard")


def update_and_comment(ctx: Context) -> None:
    a = ctx.adapter
    review = ctx.config.labels.review
    story = a.update_item(ctx.ids["story"], ItemPatch(labels=()))
    expect(not _label_in(review, story.labels), f"the review label survived labels=(): {story.labels}")
    expect(story.level is Level.STORY, f"clearing labels changed the level to {story.level.value}")
    task = a.update_item(ctx.ids["task"], ItemPatch(state=State.DONE))
    expect(task.state is State.DONE, f"the task reads {task.state.value} after state=done")
    comment = a.add_comment(Comment(ItemRef(ctx.ids["story"], Level.STORY), "Reviewed by the **conformance suite**; review label cleared."))
    expect(comment.id, "add_comment returned no id")
    ctx.note(f"review label cleared on {story.key}; task {task.key} is done; comment {comment.id} by {comment.author}")


def dates(ctx: Context) -> None:
    """A story with a start and a target date (D41): both read back as
    written, the list read carries them too, and an update moves one."""
    a = ctx.adapter
    start, target = ctx.today, ctx.today + timedelta(days=7)
    later = target + timedelta(days=1)
    made = find_or_create(ctx, WorkItem(
        Level.STORY, "Dated Story", parent=ItemRef(ctx.ids["epic"], Level.EPIC),
        start_date=start, target_date=target, external_id=ctx.xid("dated"),
    ))
    got = a.get_item(made.id or "")
    # `later` too: a resumed run may meet the item after its move
    expect(got.start_date == start and got.target_date in (target, later),
           f"{got.key} was written {start}–{target} but reads back {got.start_date}–{got.target_date}")
    listed = a.find_items(external_id=ctx.xid("dated"))
    expect([(i.start_date, i.target_date) for i in listed] == [(got.start_date, got.target_date)],
           f"the list read has {[(i.start_date, i.target_date) for i in listed]}, "
           f"get_item {got.start_date}–{got.target_date}")
    ctx.note(f"{got.key} reads back {got.start_date}–{got.target_date}, from get_item and the list read alike")
    a.update_item(made.id or "", ItemPatch(target_date=later))
    again = a.get_item(made.id or "")
    expect((again.start_date, again.target_date) == (start, later),
           f"after target_date={later} it reads {again.start_date}–{again.target_date}")
    ctx.note(f"update_item(target_date={later}) moved it; start_date stayed {again.start_date}")


def _samples(f: FieldInfo, ctx: Context) -> tuple[Any, Any] | None:
    """A value to create with and one to change to, from what the board says
    the field takes; None for a kind the suite can't make up a value for."""
    if f.kind is FieldKind.BOOLEAN:
        return True, False
    if f.kind is FieldKind.OPTION and f.options:
        if f.multi:
            return list(f.options[:2]), list(f.options[-1:])
        return f.options[0], f.options[-1]
    if f.kind is FieldKind.TEXT:
        return f"conformance {ctx.run_id}", f"conformance {ctx.run_id} edited"
    if f.kind is FieldKind.NUMBER:
        return 3, 5
    if f.kind is FieldKind.DATE:
        return ctx.today.isoformat(), (ctx.today + timedelta(days=1)).isoformat()
    return None


def _same(read: dict[str, Any], wrote: dict[str, Any]) -> bool:
    """Option names compare ignoring case, a multi-valued one as a set."""
    def norm(v: Any) -> Any:
        if isinstance(v, list):
            return frozenset(norm(x) for x in v)
        return v.lower() if isinstance(v, str) else v
    return all(norm(read.get(name)) == norm(value) for name, value in wrote.items())


def custom_fields(ctx: Context) -> None:
    """Every configured field the story type carries (D41): written at
    create, read back by get_item, then changed by update_item."""
    a = ctx.adapter
    carried = [f for f in a.describe_board().fields if Level.STORY in f.levels]
    if not carried:
        raise Skipped("the board config maps no field the story type carries ([fields])")
    first: dict[str, Any] = {}
    second: dict[str, Any] = {}
    for f in carried:
        pair = _samples(f, ctx)
        if pair is None:
            ctx.note(f"{f.name} ({f.native}) is not exercised: the suite has no {f.kind.value} value for it")
            continue
        first[f.name], second[f.name] = pair
    if not first:
        raise Skipped("no configured field is of a kind the suite can fill")
    made = find_or_create(ctx, WorkItem(
        Level.STORY, "Story With Fields", parent=ItemRef(ctx.ids["epic"], Level.EPIC),
        fields=first, external_id=ctx.xid("fields"),
    ))
    got = a.get_item(made.id or "")
    expect(_same(got.fields, first) or _same(got.fields, second),  # a resumed run may meet the changed values
           f"{got.key} was written {first} but reads back {got.fields}")
    ctx.note(f"{got.key} written with {first}; get_item reads {got.fields}")
    a.update_item(made.id or "", ItemPatch(fields=second))
    again = a.get_item(made.id or "")
    expect(_same(again.fields, second), f"after update_item(fields={second}) it reads {again.fields}")
    ctx.note(f"update_item(fields={second}) took: it reads {again.fields}")
    kinds = ", ".join(f"{f.name} = {f.native}{' (multi)' if f.multi else ''}" for f in carried)
    ctx.note(f"fields on the story type: {kinds}")


def iterations(ctx: Context) -> None:
    a = ctx.adapter
    today = ctx.today
    first = today.replace(day=1)
    start = first if first < today else today - timedelta(days=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    nxt_end = nxt.replace(day=calendar.monthrange(nxt.year, nxt.month)[1])

    # this month's iteration ends *today*: whether the tracker still takes
    # items into it answers whether it counts the end day as open
    cur, cur_new = _find_or_create_iteration(ctx, Iteration(iteration_name(ctx.config.naming, first), start=start, end=today))
    upcoming, up_new = _find_or_create_iteration(ctx, Iteration(iteration_name(ctx.config.naming, nxt), start=nxt, end=nxt_end))
    for it, new, want in ((cur, cur_new, (start, today)), (upcoming, up_new, (nxt, nxt_end))):
        expect(not new or (it.start, it.end) == want,
               f"{it.name} was written {want[0]}–{want[1]} but reads back {it.start}–{it.end}")
    expect(upcoming.state is IterationState.PLANNED, f"{upcoming.name} ({nxt}–{nxt_end}) reads {upcoming.state.value}, not planned")
    ctx.ids.update(iteration_current=cur.id or "", iteration_next=upcoming.id or "")
    if cur_new or up_new:
        ctx.note(f"dates read back as written: {cur.name} {cur.start}–{cur.end}, {upcoming.name} {upcoming.start}–{upcoming.end}")
    if cur.state is IterationState.CLOSED:
        raise Skipped(f"{cur.name} is already closed, so nothing can move into it; "
                      "re-run next month, or with a --run-id whose month has no iteration yet")
    expect(cur.state is IterationState.ACTIVE, f"{cur.name} ({cur.start}–{cur.end}) reads {cur.state.value}, not active")

    a.move_to_iteration([ctx.ids["story"], ctx.ids["task"]], cur.id or cur.name)
    a.move_to_iteration([ctx.ids["bug"]], upcoming.id or upcoming.name)
    board = _listed(ctx)
    for key, want in (("story", cur), ("task", cur), ("bug", upcoming)):
        got = board[ctx.ids[key]].iteration
        expect(got == want.id, f"the {key} reads iteration {got!r}, expected {want.name} ({want.id})")
    ctx.note(f"story + task moved into {cur.name} (active), bug into {upcoming.name} (planned); the list read confirms both")
    if cur.end == today:
        ctx.note(f"the tracker took items into {cur.name} while its end date was today — the end day is still open")


def close_iteration(ctx: Context) -> None:
    a = ctx.adapter
    ident = ctx.ids["iteration_current"]
    closed = a.close_iteration(ident)
    expect(closed.state is IterationState.CLOSED, f"close_iteration returned {closed.state.value}")
    again = a.get_iteration(ident)
    expect(again.state is IterationState.CLOSED, f"a fresh read after close says {again.state.value}")
    ctx.note(f"{again.name} closed: end date now {again.end}, and a fresh read agrees")
    try:
        a.move_to_iteration([ctx.ids["epic"]], ident)
    except ValidationError as exc:
        ctx.note(f"a closed iteration refuses new items, mapped to ValidationError: {exc}")
    else:
        raise Failed(f"closed iteration {again.name} accepted a new item")


def rollover(ctx: Context) -> None:
    """Rollover = close + move what is left (roadmap/14 §5): everything the
    closed iteration still holds that is neither done nor cancelled moves to
    the next one — board-wide, as a real rollover does, not only this run's
    items. Moving out of a *closed* iteration is the new behavior on trial."""
    a = ctx.adapter
    closed_id, next_id = ctx.ids["iteration_current"], ctx.ids["iteration_next"]
    closed, upcoming = a.get_iteration(closed_id), a.get_iteration(next_id)
    expect(closed.state is IterationState.CLOSED, f"{closed.name} reads {closed.state.value}; the close case should have closed it")

    again = a.create_iteration(Iteration(upcoming.name, start=upcoming.start, end=upcoming.end))
    expect(again.id == upcoming.id, f"create_iteration({upcoming.name!r}) returned {again.id}, not the existing {upcoming.id}")
    ctx.note(f"create_iteration({upcoming.name!r}) found the existing iteration: no duplicate")

    held = a.find_items(iteration=closed_id, limit=500)
    stray = [i.key or i.id for i in held if i.iteration != closed_id]
    expect(not stray, f"find_items(iteration={closed.name!r}) returned items in another iteration: {stray}")
    left = [i for i in held if i.state not in (State.DONE, State.CANCELLED)]
    if not left:
        raise Skipped(f"{closed.name} holds nothing unfinished ({len(held)} item(s), all done or cancelled)")

    a.move_to_iteration([i.id or "" for i in left], next_id)
    ids = {i.id for i in left}
    still = {i.id for i in a.find_items(iteration=closed_id, limit=500)}
    landed = {i.id for i in a.find_items(iteration=next_id, limit=500)}
    expect(not ids & still, f"{len(ids & still)} rolled item(s) still read {closed.name}")
    expect(ids <= landed, f"{len(ids - landed)} rolled item(s) do not read {upcoming.name}")
    keys = ", ".join(i.key or i.id or "" for i in left)
    ctx.note(f"moved out of closed {closed.name}: {keys} now read {upcoming.name}")
    followed = [i.key or i.id for i in held if i.id not in ids and i.id not in still]
    stayed = len(held) - len(left) - len(followed)
    ctx.note(f"{stayed} done or cancelled item(s) stayed in {closed.name}"
             + (f"; {', '.join(followed)} left with a moved parent" if followed else ""))


def no_delete(ctx: Context) -> None:
    wire = ctx.wire_before + Counter(m for m, _ in ctx.calls())
    ctx.note("wire totals for this run: " + ", ".join(f"{m} {n}" for m, n in sorted(wire.items())))
    expect(wire["DELETE"] == 0, f"{wire['DELETE']} DELETE request(s) were sent")


GENERIC_CASES: tuple[Case, ...] = (
    Case("describe", "describe_board is clean: the config fits and every materialized level resolves", describe),
    Case("epic", "create an epic with an external_id; find_items(external_id=…) finds exactly it", epic_round_trip),
    Case("placement", "feature, story (in the feature, review-labelled) and bug under the epic, task under the story", placement),
    Case("hierarchy", "a task straight under the epic: record whether the tracker accepts or refuses", hierarchy_probe),
    Case("update", "clear the review label, move the task to done, add a comment", update_and_comment),
    Case("dates", "a story's start and target dates read back as written, and an update moves one", dates),
    Case("fields", "each configured field on the story type: written at create, read back, changed", custom_fields),
    Case("iterations", "this month's iteration (ending today) and next month's; move items into both", iterations),
    Case("close", "close this month's iteration; a fresh read agrees; it refuses new items", close_iteration),
    Case("rollover", "what the closed iteration holds unfinished moves to the next; create_iteration finds, not duplicates", rollover),
    Case("no-delete", "no DELETE request was sent at any point in the run", no_delete, always=True),
)
