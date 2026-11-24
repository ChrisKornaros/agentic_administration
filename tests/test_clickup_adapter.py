"""Offline tests for the ClickUp adapter against the fake transport."""

import io
import json
import urllib.error
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from adapters.base import (
    AuthError,
    ConfigMismatch,
    ItemPatch,
    NotFound,
    RateLimited,
    TransportError,
    Unsupported,
    ValidationError,
)
from adapters.clickup import ClickUpAdapter
from adapters.clickup.adapter import TAG_BG, TAG_FG
from adapters.clickup.transport import UNTAG, ClickUpTransport
from server.config import BoardConfig
from server.model import Comment, InvalidWorkItem, ItemRef, Iteration, IterationState, Level, State, WorkItem
from tests import fake_clickup as fc

CONFIG = {
    "backend": "clickup",
    "connection": {"token_env": "CLICKUP_API_TOKEN", "workspace": fc.WS, "space": fc.SPACE, "sprint_folder": "Sprints",
                   "list": "Web app", "xid_field": "External ID"},
    "levels": {
        "initiative": {"collapse": "description_line", "template": "**Initiative:** {name}"},
        "epic": {"type": "Epic"},
        "feature": {"collapse": "label", "template": "feature:{name}"},
        "story": {"type": "Story"},
        "bug": {"type": str(fc.T_BUG)},
        "task": {"type": "Task"},
    },
    "states": {"backlog": "Backlog", "todo": "To Do", "in_progress": "In Progress", "done": "Done", "cancelled": "Cancelled"},
    "labels": {"review": "needs-review", "taxonomy": ["bug", "feature"]},
}
NOW = datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc)
# Sprint instants as the probe read them: a sprint starts at one instant and the one before it ends a millisecond earlier.
S1 = ("2026-11-23T11:00:00+00:00", "2026-12-07T10:59:59.999+00:00")
S2 = ("2026-12-07T11:00:00+00:00", "2026-12-21T10:59:59.999+00:00")


def make(fake=None, *, config=None, now=NOW):
    transport = fake or fc.FakeClickUp()
    cfg = BoardConfig.from_dict(config or CONFIG).check()
    return ClickUpAdapter(cfg, transport, secret=lambda name: "unused", now=lambda: now), transport


def with_levels(**levels):
    return {**CONFIG, "levels": {**CONFIG["levels"], **levels}}


def sprints(fake):
    return fake.add_sprint("Sprint 1", *S1), fake.add_sprint("Sprint 2", *S2)


# --- describe_board ----------------------------------------------------------------


def test_describe_board_reads_the_space_and_fits():
    fake = fc.FakeClickUp()
    one, two = sprints(fake)
    old = fake.add_sprint("Sprint 0", "2026-11-09T11:00:00+00:00", "2026-11-23T10:59:59.999+00:00", archived=True)
    adapter, t = make(fake)
    board = adapter.describe_board()
    assert board.problems == ()
    assert (board.backend, board.project_id, board.project_name, board.project_key) == ("clickup", fc.SPACE, "Sandbox", None)
    assert [(x.id, x.name) for x in board.types] == [("0", "Task"), ("1", "milestone"), ("1001", "Epic"), ("1002", "Story"),
                                                     ("1003", "Bug")]
    assert board.resolved == {Level.EPIC: "1001", Level.STORY: "1002", Level.BUG: "1003", Level.TASK: "0"}
    assert [(s.name, s.group) for s in board.states] == [("to do", "open"), ("backlog", "unstarted"), ("in progress", "custom"),
                                                         ("done", "done"), ("cancelled", "done"), ("complete", "closed")]
    assert [l.name for l in board.labels] == ["needs-review", "bug", "feature", "frontend", "feature:checkout"]
    assert [(c.name, c.extra["folder"]) for c in board.containers] == [("Inbox", None), ("Web app", "Features")]
    assert [(i.name, i.extra["state"], i.extra["start"], i.extra["end"]) for i in board.iterations] == [
        ("Sprint 1", "active", "2026-11-23", "2026-12-07"), ("Sprint 2", "planned", "2026-12-07", "2026-12-21"),
        ("Sprint 0", "closed", "2026-11-09", "2026-11-23")]  # the archived one comes from its own read
    assert {i.id for i in board.iterations} == {one["id"], two["id"], old["id"]}
    assert board.features == {"enabled": ["sprints", "tags"], "private": True, "time_zone": "America/New_York",
                              "sprint_folder": "Sprints"}
    assert [(m.id, m.name, m.extra) for m in board.members] == [  # the configured workspace's, not the other's
        (str(fc.U_ROBIN), "Robin", {"email": "robin@example.invalid"}), (str(fc.U_SAM), "Sam", {"email": "sam@example.invalid"})]
    assert {m for m, *_ in t.calls} == {"GET"} and len(t.calls) == 9
    assert f"/list/{fc.L_WEB}/field" in [p for _, p, *_ in t.calls]  # the home List's fields, for the idempotency key
    caps = adapter.capabilities
    assert not caps.materializes(Level.FEATURE) and not caps.states_via_transitions and not caps.native_idempotency_key


def test_describe_board_reports_every_mismatch():
    cfg = {**with_levels(epic={"type": "Initiative"}, story={"type": "Task"}, feature={"container": "list"},
                         initiative={"collapse": "component"}, bug={"label": "Defect"}),
           "connection": {**CONFIG["connection"], "sprint_folder": "Iterations", "list": "Roadmap"},
           "states": {**CONFIG["states"], "cancelled": "Won't Do"},
           "labels": {"review": "Needs-Review", "taxonomy": ["chore"]},
           "fields": {"points": "Story points"}}
    adapter, _ = make(config=cfg)
    assert adapter.describe_board().problems == (
        "connection.sprint_folder: no Folder 'Iterations' in the Space (folders: Features, Sprints)",
        "connection.list: no List 'Roadmap' in the Space outside its sprint Folder (lists: Inbox, Web app)",
        "levels.initiative: ClickUp has no components; collapse it to a label or a description_line",
        "levels.epic: no task type 'Initiative' in the workspace (types: Task, milestone, Epic, Story, Bug)",
        "levels.feature: a container level is not wired on ClickUp yet; collapse it (label or description_line)",
        "levels.bug: ClickUp stores tags in lowercase, so 'Defect' would read back as 'defect'; write it in lowercase",
        "levels.task: task type 'Task' is already the story level; ClickUp tells levels apart by type, so give each "
        "its own type or mark one with a tag (the label form)",
        "states.cancelled: no status named \"Won't Do\" in the Space "
        "(statuses: to do, backlog, in progress, done, cancelled, complete)",
        "labels: ClickUp stores tags in lowercase, so 'Needs-Review' would read back as 'needs-review'; "
        "write it in lowercase",
        "labels: no tag 'chore' in the Space (tags: needs-review, bug, feature, frontend, feature:checkout)",
        "fields: custom fields are not wired on ClickUp yet; leave [fields] out for now",
    )


def test_a_board_without_a_sprint_folder_has_no_iterations():
    conn = {k: v for k, v in CONFIG["connection"].items() if k != "sprint_folder"}
    fake = fc.FakeClickUp()
    sprints(fake)
    adapter, t = make(fake, config={**CONFIG, "connection": conn})
    board = adapter.describe_board()
    assert board.problems == () and board.iterations == () and board.features["sprint_folder"] is None
    assert len(t.calls) == 8  # no read of archived sprint Lists
    assert [c.name for c in board.containers] == ["Inbox", "Web app", "Sprint 1", "Sprint 2"]  # just Lists here
    with pytest.raises(NotFound, match="names no sprint Folder"):
        adapter.get_iteration("Sprint 1")
    with pytest.raises(NotFound, match="names no sprint Folder"):
        adapter.find_items(iteration="Sprint 1")


def test_where_an_item_goes_and_where_its_key_is_kept_are_checked_against_the_space():
    def problems(fake=None, **connection):
        conn = {k: v for k, v in {**CONFIG["connection"], **connection}.items() if v is not None}
        return make(fake, config={**CONFIG, "connection": conn})[0].describe_board().problems

    assert problems(list=None, xid_field=None) == (
        "connection.list: name the List a new item is filed in (lists: Inbox, Web app)",
        "connection.xid_field: name the text custom field that holds an item's idempotency key "
        "(add a short text field to the Space, so every List carries it)")
    assert problems(list="Sprint 1") == (  # a sprint List is no home for new work
        "connection.list: no List 'Sprint 1' in the Space outside its sprint Folder (lists: Inbox, Web app)",)
    assert problems(xid_field="Request Ref") == (
        "connection.xid_field: no custom field 'Request Ref' on the List 'Web app' (fields: External ID, Size)",)
    assert problems(xid_field="size") == (
        "connection.xid_field: 'Size' is a drop_down field; the idempotency key needs a text one (short_text or text)",)
    assert problems(list=fc.L_INBOX, xid_field=fc.FIELD_XID) == ()  # either goes by its id too


def test_no_write_goes_out_until_the_config_fits():
    conn = {k: v for k, v in CONFIG["connection"].items() if k != "list"}
    fake, epic, story, *_ = seeded()
    adapter, t = make(fake, config={**CONFIG, "connection": conn})
    writes = [
        lambda: adapter.create_item(WorkItem(Level.STORY, "x")),
        lambda: adapter.update_item(story["id"], ItemPatch(title="y")),
        lambda: adapter.add_comment(Comment(ItemRef(story["id"]), "hello")),
        lambda: adapter.create_iteration(Iteration("Sprint 1")),
        lambda: adapter.move_to_iteration([story["id"]], "Sprint 1"),
        lambda: adapter.close_iteration("Sprint 1"),
    ]
    for write in writes:
        with pytest.raises(ConfigMismatch, match="connection.list"):
            write()
    assert {m for m, *_ in t.calls} == {"GET"}
    assert adapter.get_item(story["id"]).title == story["name"]  # a read needs no clean config


def test_a_config_for_another_backend_is_refused():
    plane = {**CONFIG, "backend": "plane", "connection": {"token_env": "PLANE_API_KEY", "workspace": "ws", "project": "p"}}
    with pytest.raises(ValueError, match="got a plane config"):
        ClickUpAdapter(BoardConfig.from_dict(plane).check(), fc.FakeClickUp())


# --- one item ------------------------------------------------------------------------


def seeded():
    fake = fc.FakeClickUp()
    one, two = sprints(fake)
    epic = fake.add_task("Requester Intake", type=fc.T_EPIC)
    story = fake.add_task("Requester Can File A Bug", type=fc.T_STORY, parent=epic["id"], status="to do",
                          tags=("needs-review", "frontend"), assignee=True, added_to=(one["id"],),
                          description="As a requester\n\n- one\n- two",
                          start="2026-11-24T15:00:00+00:00", due="2026-11-30T09:00:00+00:00")
    task = fake.add_task("Wire The Form", parent=story["id"], status="in progress")
    return fake, epic, story, task, one, two


def test_read_maps_a_task_to_the_canonical_model():
    fake, epic, story, task, one, _ = seeded()
    adapter, t = make(fake)
    item = adapter.get_item(story["id"])
    assert (item.level, item.id, item.key, item.title) == (Level.STORY, story["id"], story["custom_id"], story["name"])
    assert item.parent == ItemRef(epic["id"], Level.EPIC, epic["custom_id"])  # one more read brings its level and key
    assert item.state is State.TODO and item.assignees == ("Robin",)
    assert item.labels == ("needs-review", "frontend")
    assert item.iteration == one["id"]  # the sprint it was added to; its own List is no sprint
    assert item.description == "As a requester\n\n- one\n- two"  # the Markdown read, its trailing newline dropped
    assert (item.start_date, item.target_date) == (date(2026, 11, 24), date(2026, 11, 30))
    assert item.external_id is None and item.fields == {} and item.links == ()
    reads = [(p, q) for m, p, q, _ in t.calls if p.startswith("/task/")]
    assert reads == [(f"/task/{story['id']}", {"include_markdown_description": "true"}),
                     (f"/task/{epic['id']}", {"include_markdown_description": "true"})]


def test_an_item_reads_by_its_custom_id():
    fake, _, story, task, *_ = seeded()
    adapter, t = make(fake)
    assert adapter.get_item(story["custom_id"]).id == story["id"]
    assert adapter.get_item(ItemRef(task["id"], key=task["custom_id"])).level is Level.TASK
    by_key = [q for m, p, q, _ in t.calls if p == f"/task/{story['custom_id']}"]
    assert by_key == [{"include_markdown_description": "true", "custom_task_ids": "true", "team_id": fc.WS}]


def test_a_task_outside_the_space_is_not_found():
    fake, *_ = seeded()
    elsewhere = fake.add_task("Someone Else's Work", fc.L_ELSEWHERE, space=fc.OTHER_SPACE)
    child = fake.add_task("Ours, Under Theirs", parent=elsewhere["id"])
    adapter, _ = make(fake)
    with pytest.raises(NotFound, match="in this board's Space"):
        adapter.get_item(elsewhere["id"])
    with pytest.raises(NotFound):
        adapter.get_item("86cnope")
    assert adapter.get_item(child["id"]).parent == ItemRef(elsewhere["id"])  # named, never read into the board


def test_level_comes_from_a_marker_tag_then_the_type_then_the_parent():
    cfg = {**with_levels(epic={"label": "epic"}), "labels": {"review": "needs-review", "taxonomy": []}}
    fake = fc.FakeClickUp()
    fake.tags.append("epic")
    tagged = fake.add_task("A Story Type Marked As An Epic", type=fc.T_STORY, tags=("epic",))
    milestone = fake.add_task("No Level Maps A Milestone", type=fc.T_MILESTONE)
    under = fake.add_task("And One Beneath It", type=fc.T_MILESTONE, parent=milestone["id"])
    plain = fake.add_task("A Standard Task")
    adapter, _ = make(fake, config=cfg)
    assert adapter.describe_board().resolved[Level.EPIC] == "epic"
    assert [adapter.get_item(x["id"]).level for x in (tagged, milestone, under, plain)] == [
        Level.EPIC, Level.STORY, Level.TASK, Level.TASK]


def test_a_status_the_config_does_not_name_reads_by_its_type():
    fake = fc.FakeClickUp()
    closed = fake.add_task("Shipped", status="complete")
    adapter, _ = make(fake)
    assert adapter.get_item(closed["id"]).state is State.DONE
    assert adapter.get_item(fake.add_task("Dropped", status="cancelled")["id"]).state is State.CANCELLED


# --- search ----------------------------------------------------------------------------


def test_find_items_reads_the_spaces_own_lists_and_each_task_once():
    fake, epic, story, task, one, two = seeded()
    in_sprint = fake.add_task("Lives In The Sprint", one["id"], type=fc.T_BUG, status="complete")
    fake.add_task("Someone Else's Work", fc.L_ELSEWHERE, space=fc.OTHER_SPACE)
    adapter, t = make(fake)
    items = adapter.find_items()
    assert sorted(i.title for i in items) == sorted(x["name"] for x in (epic, story, task, in_sprint))
    by_title = {i.title: i for i in items}
    assert by_title[story["name"]].parent == ItemRef(epic["id"], Level.EPIC, epic["custom_id"])  # from the same page
    assert by_title[story["name"]].iteration == one["id"] and by_title[in_sprint["name"]].iteration == one["id"]
    assert by_title[story["name"]].description == "As a requester\n\n- one\n- two"
    path, params = next((p, q) for m, p, q, _ in t.calls if p.endswith("/task"))
    assert path == f"/team/{fc.WS}/task"
    assert params == {"subtasks": "true", "include_closed": "true", "include_markdown_description": "true", "page": 0,
                      "list_ids[]": [fc.L_INBOX, fc.L_WEB, one["id"], two["id"]]}


def test_find_items_narrows_by_text_level_state_and_label():
    fake, epic, story, task, *_ = seeded()
    adapter, t = make(fake)
    assert [i.id for i in adapter.find_items("requester bug")] == [story["id"]]
    assert [i.id for i in adapter.find_items("one two")] == [story["id"]]  # the description counts
    assert [i.id for i in adapter.find_items(level=Level.EPIC)] == [epic["id"]]
    assert [i.id for i in adapter.find_items(state=State.IN_PROGRESS)] == [task["id"]]
    assert [i.id for i in adapter.find_items(label="Frontend")] == [story["id"]]
    assert [q.get("tags[]") for m, p, q, _ in t.calls if p.endswith("/task")][-1] == ["frontend"]
    assert adapter.find_items(label="front") == []  # a tag matches whole
    assert len(adapter.find_items(limit=2)) == 2


def test_find_items_walks_pages_until_the_last():
    fake = fc.FakeClickUp(page_size=2)
    made = [fake.add_task(f"Item {n}") for n in range(5)]
    adapter, t = make(fake)
    assert sorted(i.id for i in adapter.find_items()) == sorted(x["id"] for x in made)
    assert [q["page"] for m, p, q, _ in t.calls if p.endswith("/task")] == [0, 1, 2]
    assert len(adapter.find_items(limit=3)) == 3
    assert [q["page"] for m, p, q, _ in t.calls if p.endswith("/task")][3:] == [0, 1]  # it stops once it has enough


def test_find_items_by_iteration_reads_the_sprint_list_with_added_tasks():
    fake, epic, story, task, one, two = seeded()
    moved_on = fake.add_task("Carried Into The Next Sprint", added_to=(one["id"], two["id"]))
    early = datetime(2026, 12, 10, 15, 0, tzinfo=timezone.utc)  # Sprint 1 has ended, Sprint 2 is active
    adapter, t = make(fake)
    assert [i.id for i in adapter.find_items(iteration="Sprint 1")] == [story["id"], moved_on["id"]]
    path, params = [(p, q) for m, p, q, _ in t.calls if p.endswith("/task")][-1]
    assert path == f"/list/{one['id']}/task"
    assert params == {"subtasks": "true", "include_closed": "true", "include_markdown_description": "true",
                      "include_timl": "true", "page": 0}
    later, _ = make(fake, now=early)
    assert [i.id for i in later.find_items(iteration=one["id"])] == [story["id"]]  # the other's sprint is now Sprint 2
    assert [i.id for i in later.find_items(iteration="Sprint 2")] == [moved_on["id"]]
    with pytest.raises(NotFound, match="no sprint 'Sprint 9'"):
        adapter.find_items(iteration="Sprint 9")


def test_a_collapsed_level_has_no_items_and_costs_no_call():
    adapter, t = make()
    adapter.describe_board()
    before = len(t.calls)
    assert adapter.find_items(level=Level.FEATURE) == []
    assert len(t.calls) == before


# --- the idempotency key ---------------------------------------------------------------


class Stubborn:
    """The fake behind a server that misbehaves on the workspace read: one
    that ignores the custom-field filter, or one whose search lags."""

    def __init__(self, fake, *, deaf=False, lagging=False):
        self.fake, self.deaf, self.lagging = fake, deaf, lagging
        self.calls = fake.calls

    def request(self, method, path, *, params=None, body=None):
        if path.endswith("/task") and method == "GET":
            if self.lagging:
                return {"tasks": [], "last_page": True}
            if self.deaf:
                params = {k: v for k, v in (params or {}).items() if k != "custom_fields"}
        return self.fake.request(method, path, params=params, body=body)

    def get_all(self, path, params=None):
        return self.fake.get_all(path, params)


def test_an_item_is_found_by_its_external_id_exactly():
    fake, *_ = seeded()
    filed = fake.add_task("Filed Through Intake", type=fc.T_STORY, xid="Req-0042/a")
    fake.add_task("Its Sibling", type=fc.T_STORY, xid="Req-0042/b")
    adapter, t = make(fake)
    hits = adapter.find_items(external_id="Req-0042/a")
    assert [(i.id, i.external_id) for i in hits] == [(filed["id"], "Req-0042/a")]
    path, params = [(p, q) for m, p, q, _ in t.calls if p.endswith("/task")][-1]
    assert path == f"/team/{fc.WS}/task"  # one call, over the Space's own Lists
    assert json.loads(params["custom_fields"]) == [{"field_id": fc.FIELD_XID, "operator": "==", "value": "Req-0042/a"}]
    assert adapter.find_items(external_id="req-0042/a") == []  # case counts
    assert adapter.find_items(external_id="Req-0042") == []  # and a part is no match
    assert adapter.get_item(filed["id"]).external_id == "Req-0042/a"


def test_the_key_is_compared_here_too_so_an_ignored_filter_finds_the_same_task():
    fake, *_ = seeded()
    filed = fake.add_task("Filed Through Intake", type=fc.T_STORY, xid="req-0042")
    adapter, _ = make(Stubborn(fake, deaf=True))
    assert [i.id for i in adapter.find_items(external_id="req-0042")] == [filed["id"]]
    assert adapter.find_items(external_id="req-9999") == []


def test_a_task_this_process_made_is_found_while_the_search_lags():
    fake = fc.FakeClickUp()
    adapter, _ = make(Stubborn(fake, lagging=True))
    made = adapter.create_item(WorkItem(Level.STORY, "Just Filed", external_id="req-0007"))
    assert [i.id for i in adapter.find_items(external_id="req-0007")] == [made.id]
    assert adapter.find_items(external_id="req-0007", level=Level.BUG) == []
    assert adapter.find_items(external_id="req-0008") == []


def test_a_board_that_names_no_key_field_cannot_look_one_up():
    conn = {k: v for k, v in CONFIG["connection"].items() if k != "xid_field"}
    adapter, t = make(config={**CONFIG, "connection": conn})
    with pytest.raises(Unsupported, match="names no idempotency field"):
        adapter.find_items(external_id="req-0001")
    assert not [p for _, p, *_ in t.calls if p.endswith("/task")]


# --- iterations ------------------------------------------------------------------------


def test_an_iteration_reads_by_name_or_id_and_its_state_comes_from_its_instants():
    fake = fc.FakeClickUp()
    one, two = sprints(fake)
    old = fake.add_sprint("Sprint 0", "2026-11-09T11:00:00+00:00", "2026-11-23T10:59:59.999+00:00")
    adapter, _ = make(fake)
    assert adapter.get_iteration("Sprint 1") == Iteration("Sprint 1", one["id"], date(2026, 11, 23), date(2026, 12, 7),
                                                          IterationState.ACTIVE)
    assert adapter.get_iteration(two["id"]).state is IterationState.PLANNED
    assert adapter.get_iteration("Sprint 0").state is IterationState.CLOSED and old["archived"] is False
    # the instant decides, not the day: on the day both sprints touch, one has ended and the other has begun
    before, _ = make(fake, now=datetime(2026, 12, 7, 10, 0, tzinfo=timezone.utc))
    after, _ = make(fake, now=datetime(2026, 12, 7, 12, 0, tzinfo=timezone.utc))
    assert [before.get_iteration(n).state for n in ("Sprint 1", "Sprint 2")] == [IterationState.ACTIVE, IterationState.PLANNED]
    assert [after.get_iteration(n).state for n in ("Sprint 1", "Sprint 2")] == [IterationState.CLOSED, IterationState.ACTIVE]


def test_a_sprint_made_after_describe_is_found_and_a_list_elsewhere_is_not():
    fake = fc.FakeClickUp()
    sprints(fake)
    adapter, t = make(fake)
    adapter.describe_board()
    new = fake.add_sprint("Sprint 3", "2026-12-21T11:00:00+00:00", "2027-01-04T10:59:59.999+00:00")
    assert adapter.get_iteration("Sprint 3").id == new["id"]
    with pytest.raises(NotFound):
        adapter.get_iteration(fc.L_WEB)  # a List of the Space, but no sprint
    assert f"/list/{fc.L_WEB}" not in [p for m, p, *_ in t.calls]


# --- create ------------------------------------------------------------------------------


def writes(t, since=0):
    """Every request but the reads, as (method, path, body)."""
    return [(m, p, b) for m, p, _, b in t.calls[since:] if m != "GET"]


def test_create_files_the_task_in_the_home_list_with_its_key_in_one_call():
    fake = fc.FakeClickUp()
    adapter, t = make(fake)
    made = adapter.create_item(WorkItem(
        Level.EPIC, "Requester Intake", description="Why it matters\n\n- one\n- two", labels=("Frontend",),
        assignees=("robin@example.invalid",), state=State.TODO, external_id="req-0001",
        initiative=ItemRef("Growth", Level.INITIATIVE), start_date=date(2026, 11, 24), target_date=date(2026, 11, 30)))
    assert writes(t) == [("POST", f"/list/{fc.L_WEB}/task", {
        "name": "Requester Intake", "custom_item_id": fc.T_EPIC, "status": "to do",
        "markdown_content": "**Initiative:** Growth\n\nWhy it matters\n\n- one\n- two", "tags": ["frontend"],
        "assignees": [fc.U_ROBIN],
        "start_date": adapter._stamp(date(2026, 11, 24)), "start_date_time": False,
        "due_date": adapter._stamp(date(2026, 11, 30)), "due_date_time": False,
        "custom_fields": [{"id": fc.FIELD_XID, "value": "req-0001"}]})]
    assert (made.level, made.state, made.labels, made.assignees) == (Level.EPIC, State.TODO, ("frontend",), ("Robin",))
    assert made.id in fake.tasks and made.key == fake.tasks[made.id]["custom_id"]
    assert made.external_id == "req-0001" and made.initiative == ItemRef("Growth", Level.INITIATIVE)
    assert made.description == "**Initiative:** Growth\n\nWhy it matters\n\n- one\n- two"
    assert (made.start_date, made.target_date) == (date(2026, 11, 24), date(2026, 11, 30))
    assert [i.id for i in adapter.find_items(external_id="req-0001")] == [made.id]


def test_a_child_goes_into_its_parents_list_and_enters_a_sprint_as_a_second_list():
    fake = fc.FakeClickUp()
    one, _ = sprints(fake)
    epic = fake.add_task("Requester Intake", fc.L_INBOX, type=fc.T_EPIC)
    adapter, t = make(fake)
    story = adapter.create_item(WorkItem(
        Level.STORY, "Requester Can File A Bug", parent=ItemRef(epic["id"], Level.EPIC, epic["custom_id"]),
        feature=ItemRef("Checkout Flow", Level.FEATURE), iteration="Sprint 1"))
    posted = writes(t)
    assert [(m, p) for m, p, _ in posted] == [
        ("POST", f"/space/{fc.SPACE}/tag"),  # the collapse rule's tag is new to the Space
        ("POST", f"/list/{fc.L_INBOX}/task"),  # the epic's List, not the home List
        ("POST", f"/list/{one['id']}/task/{story.id}")]
    assert posted[0][2] == {"tag": {"name": "feature:checkout flow", "tag_fg": TAG_FG, "tag_bg": TAG_BG}}
    assert posted[1][2] == {"name": "Requester Can File A Bug", "custom_item_id": fc.T_STORY, "status": "backlog",
                            "tags": ["feature:checkout flow"], "parent": epic["id"]}
    assert story.parent == ItemRef(epic["id"], Level.EPIC, epic["custom_id"]) and story.iteration == one["id"]
    assert story.labels == ("feature:checkout flow",) and story.feature == ItemRef("Checkout Flow", Level.FEATURE)
    assert fake.tasks[story.id]["list"]["id"] == fc.L_INBOX and "feature:checkout flow" in fake.tags
    # a tag the Space already has is not made again
    before = len(t.calls)
    adapter.create_item(WorkItem(Level.BUG, "Checkout Rejects A Valid Card", feature=ItemRef("Checkout", Level.FEATURE)))
    assert [(m, p) for m, p, _ in writes(t, before)] == [("POST", f"/list/{fc.L_WEB}/task")]


def test_a_level_marked_by_a_tag_rides_the_story_type_and_keeps_its_tag():
    cfg = {**with_levels(epic={"label": "epic"}), "labels": {"review": "needs-review", "taxonomy": []}}
    fake = fc.FakeClickUp()
    fake.tags.append("epic")
    adapter, t = make(fake, config=cfg)
    epic = adapter.create_item(WorkItem(Level.EPIC, "A Marked Epic", labels=("frontend",)))
    body = writes(t)[0][2]
    assert (body["custom_item_id"], body["tags"]) == (fc.T_STORY, ["frontend", "epic"])
    assert epic.level is Level.EPIC
    cleared = adapter.update_item(epic.id, ItemPatch(labels=()))
    assert cleared.labels == ("epic",) and cleared.level is Level.EPIC  # labels never change a level
    assert [(m, p) for m, p, _ in writes(t)][1:] == [("DELETE", f"/task/{epic.id}/tag/frontend")]


def test_create_refuses_what_it_cannot_write_before_any_call():
    fake, *_ = seeded()
    elsewhere = fake.add_task("Someone Else's Work", fc.L_ELSEWHERE, space=fc.OTHER_SPACE)
    adapter, t = make(fake)
    refusals = [
        (WorkItem(Level.STORY, "x", links=("https://example.invalid/a",)), Unsupported, "links are not written"),
        (WorkItem(Level.STORY, "x", fields={"size": "S"}), Unsupported, "custom fields are not wired"),
        (WorkItem(Level.STORY, "x", component="web"), Unsupported, "no components"),
        (WorkItem(Level.FEATURE, "x"), Unsupported, "collapses on this board"),
        (WorkItem(Level.STORY, "x", assignees=("nobody",)), ValidationError, r"no member 'nobody' in the workspace \(members: Robin, Sam\)"),
        (WorkItem(Level.STORY, "x", iteration="Sprint 9"), NotFound, "no sprint 'Sprint 9'"),
        (WorkItem(Level.TASK, "x", parent=ItemRef(elsewhere["id"])), NotFound, "in this board's Space"),
        (WorkItem(Level.TASK, "x"), InvalidWorkItem, "must have a parent"),
    ]
    for item, error, message in refusals:
        with pytest.raises(error, match=message):
            adapter.create_item(item)
    assert writes(t) == []


# --- update ------------------------------------------------------------------------------


def test_update_changes_what_the_patch_names_in_one_call_and_tags_one_at_a_time():
    fake, epic, story, task, one, _ = seeded()
    other = fake.add_task("Another Epic", type=fc.T_EPIC)
    adapter, t = make(fake)
    got = adapter.update_item(story["custom_id"], ItemPatch(
        title="Requester Can Report A Bug", description="Rewritten", state=State.IN_PROGRESS, assignees=("sam",),
        parent=ItemRef(other["id"], Level.EPIC), start_date=date(2026, 11, 25), target_date=date(2026, 12, 1),
        labels=("Frontend", "feature:checkout")))
    sid = story["id"]
    assert writes(t) == [
        ("PUT", f"/task/{sid}", {
            "name": "Requester Can Report A Bug", "markdown_content": "Rewritten", "status": "in progress",
            "assignees": {"add": [fc.U_SAM], "rem": [fc.U_ROBIN]}, "parent": other["id"],
            "start_date": adapter._stamp(date(2026, 11, 25)), "start_date_time": False,
            "due_date": adapter._stamp(date(2026, 12, 1)), "due_date_time": False}),
        ("POST", f"/task/{sid}/tag/feature%3Acheckout", None),
        ("DELETE", f"/task/{sid}/tag/needs-review", None)]
    assert (got.title, got.description, got.state, got.assignees) == (
        "Requester Can Report A Bug", "Rewritten", State.IN_PROGRESS, ("Sam",))
    assert got.labels == ("frontend", "feature:checkout")
    assert got.parent == ItemRef(other["id"], Level.EPIC, other["custom_id"]) and got.iteration == one["id"]
    assert (got.start_date, got.target_date) == (date(2026, 11, 25), date(2026, 12, 1))


def test_update_sends_only_what_changes():
    fake, epic, story, task, *_ = seeded()
    adapter, t = make(fake)
    assert adapter.update_item(task["id"], ItemPatch(state=State.DONE)).state is State.DONE
    adapter.update_item(story["id"], ItemPatch(assignees=("Robin",), labels=("needs-review", "frontend")))  # as it is
    cleared = adapter.update_item(story["id"], ItemPatch(description="", assignees=()))
    assert writes(t) == [
        ("PUT", f"/task/{task['id']}", {"status": "done"}),
        ("PUT", f"/task/{story['id']}", {"description": " ", "assignees": {"add": [], "rem": [fc.U_ROBIN]}})]
    assert cleared.description == "" and cleared.assignees == ()


def test_a_tag_is_quoted_whole_in_its_path_and_the_only_delete_takes_a_tag_off_a_task():
    fake, epic, story, *_ = seeded()
    fake.tags += ["r&d", "needs design"]
    adapter, t = make(fake)
    adapter.update_item(story["id"], ItemPatch(labels=("r&d", "needs design")))
    assert adapter.update_item(story["id"], ItemPatch(labels=())).labels == ()
    sent = [(m, p) for m, p, _ in writes(t)]
    assert sent[:2] == [("POST", f"/task/{story['id']}/tag/r%26d"), ("POST", f"/task/{story['id']}/tag/needs%20design")]
    deletes = [p for m, p in sent if m == "DELETE"]
    assert len(deletes) == 4 and all(UNTAG.match(p) for p in deletes) and len(sent) == 6
    # the task is still there, and so is every tag in the Space
    assert story["id"] in fake.tasks and {"r&d", "needs design", "needs-review", "frontend"} <= set(fake.tags)


def test_a_tag_with_a_slash_is_refused_before_anything_is_written_and_one_already_on_stays():
    # ClickUp answered 404 or 400 to every form of such a name in the address (probe, 2026-11-24).
    fake, epic, story, *_ = seeded()
    fake.tags += ["ui/ux"]
    adapter, t = make(fake)
    with pytest.raises(Unsupported, match="slash in its name.*ui/ux.*Nothing was written"):
        adapter.update_item(story["id"], ItemPatch(title="Renamed", labels=("ui/ux",)))
    assert writes(t) == [] and fake.tasks[story["id"]]["name"] == story["name"]  # the title did not go either
    tagged = fake.add_task("Carries One Already", tags=("ui/ux",))
    since = len(t.calls)
    kept = adapter.update_item(tagged["id"], ItemPatch(labels=("ui/ux", "frontend")))
    assert kept.labels == ("ui/ux", "frontend") and [m for m, *_ in writes(t, since)] == ["POST"]
    with pytest.raises(Unsupported, match="slash in its name"):
        adapter.update_item(tagged["id"], ItemPatch(labels=("frontend",)))  # taking it off uses the same address


def test_update_refuses_before_any_call_and_never_writes_outside_the_space():
    fake, epic, story, *_ = seeded()
    elsewhere = fake.add_task("Someone Else's Work", fc.L_ELSEWHERE, space=fc.OTHER_SPACE)
    adapter, t = make(fake)
    refusals = [
        (story["id"], ItemPatch(), ValidationError, "the patch is empty"),
        (story["id"], ItemPatch(feature=ItemRef("Checkout", Level.FEATURE)), Unsupported, "feature collapses on ClickUp"),
        (story["id"], ItemPatch(links=("https://example.invalid/a",)), Unsupported, "links are not written"),
        (story["id"], ItemPatch(fields={"size": "S"}), Unsupported, "custom fields are not wired"),
        (story["id"], ItemPatch(title="y", assignees=("nobody",)), ValidationError, "no member 'nobody'"),
        (story["id"], ItemPatch(title="y", parent=ItemRef(elsewhere["id"])), NotFound, "in this board's Space"),
        (elsewhere["id"], ItemPatch(title="Ours Now", labels=()), NotFound, "in this board's Space"),
        ("86cnope", ItemPatch(title="y"), NotFound, "no such task"),
    ]
    for ref, patch, error, message in refusals:
        with pytest.raises(error, match=message):
            adapter.update_item(ref, patch)
    assert writes(t) == [] and elsewhere["name"] == "Someone Else's Work"


# --- comments ------------------------------------------------------------------------------


def test_a_comment_goes_as_text_and_comes_back_with_its_id_author_and_time():
    fake, epic, story, *_ = seeded()
    elsewhere = fake.add_task("Someone Else's Work", fc.L_ELSEWHERE, space=fc.OTHER_SPACE)
    adapter, t = make(fake)
    made = adapter.add_comment(Comment(ItemRef(story["id"], Level.STORY, story["custom_id"]), "Reviewed: **ready**."))
    assert writes(t) == [("POST", f"/task/{story['id']}/comment", {"comment_text": "Reviewed: **ready**.", "notify_all": False})]
    assert (made.id, made.author, made.body) == (fake.comments[0]["id"], "Robin", "Reviewed: **ready**.")
    assert made.created_at == datetime.fromisoformat(fc.COMMENTED)
    with pytest.raises(NotFound, match="in this board's Space"):
        adapter.add_comment(Comment(ItemRef(elsewhere["id"]), "not ours to comment on"))
    assert len(fake.comments) == 1


# --- sprints: found, joined, never made or closed ------------------------------------------

S0 = ("2026-11-09T11:00:00+00:00", "2026-11-23T10:59:59.999+00:00")  # over by NOW


def test_a_sprint_is_found_never_made_and_closes_by_itself():
    fake = fc.FakeClickUp()
    one, two = sprints(fake)
    fake.add_sprint("Sprint 0", *S0)
    adapter, t = make(fake)
    assert adapter.create_iteration(Iteration("Sprint 2")).id == two["id"]
    same = adapter.create_iteration(Iteration("Sprint 2", start=date(2026, 12, 7), end=date(2026, 12, 21)))
    assert (same.id, same.state) == (two["id"], IterationState.PLANNED)
    with pytest.raises(ValidationError, match="already exists, dated 2026-12-07–2026-12-21"):
        adapter.create_iteration(Iteration("Sprint 2", start=date(2026, 12, 8)))
    with pytest.raises(Unsupported, match="cannot make a sprint, so 'Sprint 3' has to be made in ClickUp"):
        adapter.create_iteration(Iteration("Sprint 3", start=date(2026, 12, 21), end=date(2027, 1, 4)))
    assert adapter.close_iteration("Sprint 0").state is IterationState.CLOSED  # already over: nothing to do
    with pytest.raises(Unsupported, match="closes a sprint itself when its end passes, and 'Sprint 1' runs to 2026-12-07"):
        adapter.close_iteration(one["id"])
    assert writes(t) == []


def test_a_task_enters_a_sprint_by_being_added_to_its_list():
    fake, epic, story, task, one, two = seeded()
    fake.add_sprint("Sprint 0", *S0)
    lives = fake.add_task("Lives In The Sprint", two["id"])
    elsewhere = fake.add_task("Someone Else's Work", fc.L_ELSEWHERE, space=fc.OTHER_SPACE)
    adapter, t = make(fake)
    adapter.move_to_iteration([story["id"], ItemRef(task["id"]), story["custom_id"], lives["id"]], "Sprint 2")
    assert writes(t) == [("POST", f"/list/{two['id']}/task/{story['id']}", None),  # once, though named twice
                         ("POST", f"/list/{two['id']}/task/{task['id']}", None)]  # and not the one already there
    assert fake.tasks[story["id"]]["list"]["id"] == fc.L_WEB  # still in its own List
    assert adapter.get_item(story["id"]).iteration == one["id"]  # and in Sprint 1, the active one
    later, _ = make(fake, now=datetime(2026, 12, 10, 15, 0, tzinfo=timezone.utc))
    assert later.get_item(story["id"]).iteration == two["id"]  # once Sprint 1 has ended it reads the next
    with pytest.raises(ValidationError, match="sprint 'Sprint 0' is closed"):
        adapter.move_to_iteration([epic["id"]], "Sprint 0")
    with pytest.raises(NotFound, match="in this board's Space"):
        adapter.move_to_iteration([epic["id"], elsewhere["id"]], "Sprint 2")  # nothing moves when one is not ours
    with pytest.raises(NotFound, match="no sprint"):
        adapter.move_to_iteration([epic["id"]], fc.L_WEB)  # a List of the Space, but no sprint
    assert len(writes(t)) == 2


# --- dates ---------------------------------------------------------------------------------


def test_a_date_is_written_where_clickup_keeps_one_or_at_noon_utc_without_the_zone():
    fake = fc.FakeClickUp()
    fake.user["timezone"] = "Nowhere/Unknown"
    unknown, _ = make(fake)
    unknown.describe_board()
    assert unknown._stamp(date(2026, 11, 30)) == int(fc.ms("2026-11-30T12:00:00+00:00"))
    try:
        ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        return  # this Python has no zone database (Windows without tzdata): the case above is the one it runs
    known, _ = make()
    known.describe_board()
    assert known._stamp(date(2026, 11, 30)) == int(fc.ms("2026-11-30T04:00:00-05:00"))
    assert known._stamp(date(2026, 7, 1)) == int(fc.ms("2026-07-01T04:00:00-04:00"))


# --- the transport ---------------------------------------------------------------------


class Answer:
    def __init__(self, text):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._text.encode()


def transport(answers, **kwargs):
    sent = []

    def opener(req, timeout):
        sent.append(req)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Answer(answer)

    return ClickUpTransport(lambda: "pk_not_a_real_token", throttle=0, opener=opener, **kwargs), sent


def refusal(status, body, headers=None):
    return urllib.error.HTTPError("https://example.invalid", status, "x", headers or {}, io.BytesIO(body.encode()))


def test_the_token_is_the_whole_authorization_header_and_a_list_repeats_its_key():
    t, sent = transport(['{"tasks": [], "last_page": true}'])
    assert t.request("GET", "/team/9001/task", params={"list_ids[]": ["a", "b"], "page": 0, "skip": None}) == {
        "tasks": [], "last_page": True}
    req = sent[0]
    assert req.get_header("Authorization") == "pk_not_a_real_token"  # no Bearer
    assert req.full_url == "https://api.clickup.com/api/v2/team/9001/task?list_ids%5B%5D=a&list_ids%5B%5D=b&page=0"
    assert req.get_method() == "GET" and t.log == [("GET", "/team/9001/task")]


def test_get_all_walks_task_pages_and_takes_any_other_envelope_whole():
    t, sent = transport(['{"tasks": [{"id": "a"}], "last_page": false}', '{"tasks": [{"id": "b"}], "last_page": true}',
                         '{"folders": [{"id": "f"}]}'])
    assert t.get_all("/list/1/task", {"subtasks": "true"}) == [{"id": "a"}, {"id": "b"}]
    assert [r.full_url.rsplit("?", 1)[1] for r in sent] == ["subtasks=true", "subtasks=true&page=1"]
    assert t.get_all("/space/1/folder") == [{"id": "f"}]


@pytest.mark.parametrize("status, kind", [(401, AuthError), (403, AuthError), (404, NotFound), (429, RateLimited),
                                          (400, ValidationError), (500, TransportError)])
def test_every_failure_maps_onto_the_taxonomy(status, kind):
    t, _ = transport([refusal(status, '{"err": "Team not authorized", "ECODE": "OAUTH_027"}')])
    with pytest.raises(kind) as exc:
        t.request("GET", "/list/1")
    assert "pk_not_a_real_token" not in f"{exc.value} {exc.value.detail}"
    if status != 429:
        assert "Team not authorized (OAUTH_027)" in str(exc.value)


def test_a_task_that_is_not_there_is_not_found_though_clickup_answers_401():
    body = '{"err": "Team not authorized", "ECODE": "OAUTH_027"}'
    t, _ = transport([refusal(401, body), refusal(401, body), refusal(401, '{"err": "some other refusal", "ECODE": "OAUTH_000"}')])
    with pytest.raises(NotFound, match="no such task, or one this token cannot reach"):
        t.request("GET", "/task/not-a-task-id")
    with pytest.raises(AuthError):  # the same code anywhere else is about access
        t.request("GET", "/space/1")
    with pytest.raises(AuthError):  # and any other 401 on a task is the token
        t.request("GET", "/task/86c1")


def test_a_write_sends_its_body_as_json():
    t, sent = transport(['{"id": "86c1"}'])
    assert t.request("POST", "/list/9301/task", body={"name": "x"}) == {"id": "86c1"}
    assert sent[0].data == b'{"name": "x"}' and sent[0].get_header("Content-type") == "application/json"
    assert sent[0].get_method() == "POST"


def test_the_only_delete_the_transport_sends_takes_a_tag_off_a_task():
    t, sent = transport(["{}"])
    for path in ("/task/86c1", "/list/9301", "/list/9301/task/86c1", "/space/9101/tag/frontend", "/task/86c1/comment",
                 "/task/86c1/field/fld-9701", "/task/86c1/tag/a/b", "/task/86c1/tag/"):
        with pytest.raises(Unsupported, match="nothing is deleted"):
            t.request("DELETE", path)
    with pytest.raises(Unsupported):
        t.request("PATCH", "/task/86c1")
    assert sent == [] and t.log == []  # refused before the token is read or anything goes out
    assert t.request("DELETE", "/task/86c1/tag/needs%20review") == {}
    assert sent[0].get_method() == "DELETE" and t.log == [("DELETE", "/task/86c1/tag/needs%20review")]


def test_a_missing_token_is_an_auth_error_and_an_unreadable_answer_a_transport_error():
    from server.secrets import SecretUnavailable

    def missing():
        raise SecretUnavailable("CLICKUP_API_TOKEN is not set")

    with pytest.raises(AuthError, match="CLICKUP_API_TOKEN is not set"):
        ClickUpTransport(missing, opener=None).request("GET", "/user")
    t, _ = transport(["<html>a wall</html>"])
    with pytest.raises(TransportError, match="non-JSON"):
        t.request("GET", "/user")


# --- the custom id of a task just made ------------------------------------------------


class LateKeys(fc.FakeClickUp):
    """ClickUp as seen live: a new task's custom id is missing from the first reads of it.
    With `never`, the Space issues none, and every task is `age` old."""

    def __init__(self, late=1, never=False, age_ms=None):
        super().__init__()
        self.late, self.never, self.age_ms, self.reads, self.fresh = late, never, age_ms, {}, set()

    def request(self, method, path, *, params=None, body=None):
        out = super().request(method, path, params=params, body=body)
        if method == "GET" and path.startswith("/task/") and isinstance(out, dict) and out.get("id"):
            seen = self.reads[out["id"]] = self.reads.get(out["id"], 0) + 1
            out = dict(out)
            if self.never or (out["id"] in self.fresh and seen <= self.late):
                out["custom_id"] = None
            if self.age_ms is not None:
                out["date_created"] = str(self.age_ms)
        return out

    def _write(self, method, path, body):
        out = super()._write(method, path, body)
        if method == "POST" and path.endswith("/task") and isinstance(out, dict) and out.get("id"):
            self.fresh.add(out["id"])
        return out


def late(**kwargs):
    fake = LateKeys(**kwargs)
    waits: list[float] = []
    cfg = BoardConfig.from_dict(CONFIG).check()
    return ClickUpAdapter(cfg, fake, secret=lambda name: "unused", now=lambda: NOW, sleep=waits.append), fake, waits


def test_create_waits_a_moment_for_the_custom_id_clickup_adds_late():
    adapter, fake, waits = late(late=1)
    made = adapter.create_item(WorkItem(Level.STORY, "Late Key"))
    assert made.key == fake.tasks[made.id]["custom_id"] and waits == [1.0]
    adapter, fake, waits = late(late=5)  # it never comes in time: the item is returned without a key
    made = adapter.create_item(WorkItem(Level.STORY, "No Key Yet"))
    assert made.key is None and made.id in fake.tasks and waits == [1.0, 2.0]


def test_create_does_not_wait_when_the_key_came_back_or_the_space_issues_none():
    adapter, fake, waits = late(late=0)
    assert adapter.create_item(WorkItem(Level.STORY, "Keyed At Once")).key and waits == []
    old = int((NOW.timestamp() - 3600) * 1000)
    adapter, fake, waits = late(never=True, age_ms=old)
    parent = fake.add_task("An Older Epic", type=fc.T_EPIC)
    made = adapter.create_item(WorkItem(Level.STORY, "Under It", parent=ItemRef(parent["id"])))
    assert made.key is None and waits == []  # the parent, an hour old with no custom id, showed the Space issues none
