"""Offline tests for the ClickUp adapter's read side against the fake transport."""

import io
import urllib.error
from datetime import date, datetime, timezone

import pytest

from adapters.base import AuthError, ItemPatch, NotFound, RateLimited, TransportError, Unsupported, ValidationError
from adapters.clickup import ClickUpAdapter
from adapters.clickup.transport import ClickUpTransport
from server.config import BoardConfig
from server.model import Comment, ItemRef, Iteration, IterationState, Level, Materialization, State, WorkItem
from tests import fake_clickup as fc

CONFIG = {
    "backend": "clickup",
    "connection": {"token_env": "CLICKUP_API_TOKEN", "workspace": fc.WS, "space": fc.SPACE, "sprint_folder": "Sprints"},
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
    assert board.members == ()  # not read yet
    assert {m for m, *_ in t.calls} == {"GET"} and len(t.calls) == 7
    caps = adapter.capabilities
    assert not caps.materializes(Level.FEATURE) and not caps.states_via_transitions and not caps.native_idempotency_key


def test_describe_board_reports_every_mismatch():
    cfg = {**with_levels(epic={"type": "Initiative"}, story={"type": "Task"}, feature={"container": "list"},
                         initiative={"collapse": "component"}, bug={"label": "Defect"}),
           "connection": {**CONFIG["connection"], "sprint_folder": "Iterations"},
           "states": {**CONFIG["states"], "cancelled": "Won't Do"},
           "labels": {"review": "Needs-Review", "taxonomy": ["chore"]},
           "fields": {"points": "Story points"}}
    adapter, _ = make(config=cfg)
    assert adapter.describe_board().problems == (
        "connection.sprint_folder: no Folder 'Iterations' in the Space (folders: Features, Sprints)",
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
    assert len(t.calls) == 6  # no read of archived sprint Lists
    assert [c.name for c in board.containers] == ["Inbox", "Web app", "Sprint 1", "Sprint 2"]  # just Lists here
    with pytest.raises(NotFound, match="names no sprint Folder"):
        adapter.get_iteration("Sprint 1")
    with pytest.raises(NotFound, match="names no sprint Folder"):
        adapter.find_items(iteration="Sprint 1")


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


def test_what_the_read_side_does_not_search():
    adapter, t = make()
    adapter.describe_board()
    before = len(t.calls)
    with pytest.raises(Unsupported, match="idempotency key is not wired"):
        adapter.find_items(external_id="req-0001")
    assert adapter.find_items(level=Level.FEATURE) == []  # a collapsed level has no items of its own
    assert len(t.calls) == before


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


# --- writes are not wired ----------------------------------------------------------------


def test_every_write_is_refused_before_any_call():
    adapter, t = make()
    ref = ItemRef("86c1")
    writes = [
        lambda: adapter.create_item(WorkItem(Level.STORY, "x")),
        lambda: adapter.update_item(ref, ItemPatch(title="y")),
        lambda: adapter.add_comment(Comment(ref, "hello")),
        lambda: adapter.create_iteration(Iteration("202612")),
        lambda: adapter.move_to_iteration([ref], "202612"),
        lambda: adapter.close_iteration("202612"),
    ]
    for write in writes:
        with pytest.raises(Unsupported, match="writes nothing"):
            write()
    assert t.calls == []


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


def test_a_missing_token_is_an_auth_error_and_an_unreadable_answer_a_transport_error():
    from server.secrets import SecretUnavailable

    def missing():
        raise SecretUnavailable("CLICKUP_API_TOKEN is not set")

    with pytest.raises(AuthError, match="CLICKUP_API_TOKEN is not set"):
        ClickUpTransport(missing, opener=None).request("GET", "/user")
    t, _ = transport(["<html>a wall</html>"])
    with pytest.raises(TransportError, match="non-JSON"):
        t.request("GET", "/user")
