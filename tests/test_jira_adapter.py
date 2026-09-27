"""Offline tests for the Jira adapter against the fake transport."""

from datetime import date

import pytest

from adapters.base import AuthError, ConfigMismatch, ItemPatch, NotFound, Unsupported, ValidationError
from adapters.jira import JiraAdapter
from adapters.jira.transport import JiraTransport
from server.config import BoardConfig
from server.model import Comment, ItemRef, Iteration, IterationState, Level, State, WorkItem
from tests import fake_jira as fj

CONFIG = {
    "backend": "jira",
    "connection": {"token_env": "JIRA_API_TOKEN", "user_env": "JIRA_USER", "site": "example.atlassian.net",
                   "project_key": fj.KEY, "board_id": int(fj.BOARD)},
    "levels": {
        "initiative": {"collapse": "description_line", "template": "**Initiative:** {name}"},
        "epic": {"type": "Epic"},
        "feature": {"collapse": "label", "template": "feature:{name}"},
        "story": {"type": "Story"},
        "bug": {"type": fj.T_BUG},
        "task": {"type": "Sub-task"},
    },
    "states": {"backlog": "Backlog", "todo": "To Do", "in_progress": "In Progress", "done": "Done", "cancelled": "Cancelled"},
    "labels": {"review": "needs-review", "taxonomy": ["bug", "feature"]},
    "naming": {"iteration": "YYYYMM"},
}


def make(fake=None, *, config=None, today=date(2026, 9, 27)):
    transport = fake or fj.FakeJira()
    cfg = BoardConfig.from_dict(config or CONFIG).check()
    return JiraAdapter(cfg, transport, secret=lambda name: "unused", today=lambda: today), transport


def with_levels(**levels):
    return {**CONFIG, "levels": {**CONFIG["levels"], **levels}}


# --- describe_board: the read-before-write gate --------------------------------


def test_describe_board_resolves_types_statuses_and_fits():
    adapter, t = make()
    board = adapter.describe_board()
    assert board.problems == ()
    assert board.project_key == fj.KEY and board.project_id == fj.PID
    assert board.resolved == {Level.EPIC: fj.T_EPIC, Level.STORY: fj.T_STORY, Level.BUG: fj.T_BUG, Level.TASK: fj.T_SUB}
    assert [s.name for s in board.states] == ["Backlog", "To Do", "In Progress", "Cancelled", "Done"]
    assert [m.name for m in board.members] == ["Chris"]  # the app user is not assignable here
    assert board.features["sprint_field"] == fj.SPRINT_FIELD and board.features["board_type"] == "scrum"
    # labels are free-form: the site's plus the config's, so a fresh project fits
    assert {l.name for l in board.labels} == {"bug", "docs", "needs-review", "feature"}
    assert {m for m, *_ in t.calls} == {"GET"}
    assert not adapter.capabilities.materializes(Level.FEATURE) and adapter.capabilities.states_via_transitions


def test_describe_board_reports_every_mismatch_and_writes_refuse():
    cfg = {**with_levels(task={"type": "Task"}, feature={"container": "module"}),
           "states": {**CONFIG["states"], "cancelled": "Won't Do"},
           "labels": {"review": "needs review", "taxonomy": []}}
    adapter, t = make(fj.FakeJira(board_type="kanban"), config=cfg)
    board = adapter.describe_board()
    assert board.problems == (
        "levels.feature: Jira has no container level; collapse it (label, component or description_line)",
        "levels.task: issue type 'Task' is at hierarchy level 0; a task needs level -1 (a sub-task type)",
        "states.cancelled: no status named \"Won't Do\" in the project "
        "(statuses: Backlog, To Do, In Progress, Cancelled, Done)",
        "labels: Jira labels cannot contain spaces: 'needs review'",
        "board 2 is a 'kanban' board; sprints need a scrum board",
    )
    with pytest.raises(ConfigMismatch):
        adapter.create_item(WorkItem(Level.STORY, "x"))
    assert t.bodies("POST", "") == []


def test_feature_and_initiative_cannot_be_jira_levels_below_premium():
    adapter, _ = make(config=with_levels(feature={"type": "Story"}, initiative={"type": "Epic"}))
    problems = adapter.describe_board().problems
    assert "levels.feature: Jira has no hierarchy level between Epic and Story; collapse it" in problems
    assert ("levels.initiative: issue type 'Epic' is at hierarchy level 1; an initiative needs a Premium "
            "level above Epic (2+), or collapse it") in problems


def test_unresolved_credentials_are_an_auth_error():
    cfg = BoardConfig.from_dict(CONFIG).check()

    def missing(name):
        from server.secrets import SecretUnavailable
        raise SecretUnavailable(f"{name} is not set")

    adapter = JiraAdapter(cfg, JiraTransport("example.atlassian.net", lambda: missing("JIRA_USER"),
                                             lambda: missing("JIRA_API_TOKEN"), opener=None))
    with pytest.raises(AuthError, match="JIRA_USER is not set"):
        adapter.describe_board()


# --- reads -----------------------------------------------------------------------


def seeded():
    fake = fj.FakeJira()
    epic = fake.add_issue(fj.T_EPIC, "Requester Intake")
    sprint = fake.add_sprint("202609", "active", "2026-09-01T00:00:00-04:00", "2026-09-30T23:59:00-04:00")
    story = fake.add_issue(
        fj.T_STORY, "Requester Can File A Bug", _parent=epic["id"], labels=["needs-review", "xid:req-0001"],
        status={"id": fj.S_TODO, "name": "To Do", "statusCategory": {"key": "new"}},
        assignee={"accountId": fj.U_CHRIS, "displayName": "Chris"},
        components=[{"id": fj.C_INTAKE, "name": "Intake"}],
        description={"version": 1, "type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "As a requester"}]}]},
        **{fj.SPRINT_FIELD: [{"id": 7, "state": "closed"}, sprint]},
    )
    return fake, epic, story, sprint


def test_read_maps_an_issue_to_the_canonical_model():
    fake, epic, story, sprint = seeded()
    adapter, _ = make(fake)
    item = adapter.get_item(story["key"])
    assert item.level is Level.STORY and item.key == story["key"] and item.id == story["id"]
    assert item.parent == ItemRef(epic["id"], Level.EPIC, epic["key"])  # the parent's key comes along
    assert item.state is State.TODO
    assert item.labels == ("needs-review",) and item.external_id == "req-0001"  # xid hidden from labels
    assert item.assignees == ("Chris",) and item.component == "Intake"
    assert item.iteration == str(sprint["id"])  # the open sprint, not the closed one before it
    assert item.description == "As a requester"
    assert adapter.get_item(story["id"]).key == story["key"]
    with pytest.raises(NotFound):
        adapter.get_item("AA-999")


def test_find_items_by_external_id_text_level_and_state():
    fake, epic, story, _ = seeded()
    adapter, t = make(fake)
    assert [i.key for i in adapter.find_items(external_id="req-0001")] == [story["key"]]
    assert adapter.find_items(external_id="req-0002") == []
    assert t.calls[-1][2]["jql"] == 'project = "AA" AND labels = "xid:req-0002" ORDER BY created DESC'
    assert [i.key for i in adapter.find_items("file bug")] == [story["key"]]
    assert [i.key for i in adapter.find_items(level=Level.EPIC)] == [epic["key"]]
    assert [i.key for i in adapter.find_items(state=State.TODO)] == [story["key"]]
    assert adapter.find_items("anything", level=Level.FEATURE) == []  # a collapsed level has no items
    assert len(adapter.find_items(limit=1)) == 1


def test_search_pages_follow_the_next_page_token():
    fake = fj.FakeJira()
    for n in range(120):
        fake.add_issue(fj.T_STORY, f"Story {n}")
    adapter, t = make(fake)
    assert len(adapter.find_items(limit=120)) == 120
    pages = [c[2] for c in t.calls if c[1] == "/rest/api/3/search/jql"]
    assert [(p["nextPageToken"], p["maxResults"]) for p in pages] == [(None, 100), ("100", 20)]


# --- writes ----------------------------------------------------------------------


def test_create_story_under_epic_with_review_xid_feature_and_initiative():
    fake, epic, _, sprint = seeded()
    adapter, t = make(fake)
    made = adapter.create_item(WorkItem(
        Level.STORY, "Requester Files A Story", description="As a requester I can **file**.",
        parent=ItemRef(epic["key"], Level.EPIC), feature=ItemRef("Intake Flow", Level.FEATURE),
        labels=("needs-review",), assignees=("chris@example.invalid",), component="Intake",
        iteration="202609", external_id="20260927-file/1",
    ))
    body = t.bodies("POST", "/rest/api/3/issue")[0]["fields"]
    assert body["issuetype"] == {"id": fj.T_STORY} and body["parent"] == {"key": epic["key"]}
    assert body["labels"] == ["needs-review", "feature:Intake-Flow", "xid:20260927-file/1"]
    assert body["assignee"] == {"accountId": fj.U_CHRIS} and body["components"] == [{"id": fj.C_INTAKE}]
    assert body[fj.SPRINT_FIELD] == sprint["id"]
    assert body["description"]["content"][0]["content"][1] == {"type": "text", "text": "file", "marks": [{"type": "strong"}]}
    assert made.key and made.parent.id == epic["id"] and made.state is State.BACKLOG
    assert made.labels == ("needs-review", "feature:Intake-Flow") and made.external_id == "20260927-file/1"
    assert made.iteration == str(sprint["id"]) and made.feature == ItemRef("Intake Flow", Level.FEATURE)
    assert not t.bodies("POST", "/transitions")  # it started in Backlog, as asked

    adapter.create_item(WorkItem(Level.EPIC, "Big Epic", initiative=ItemRef("Grow", Level.INITIATIVE)))
    epic_body = t.bodies("POST", "/rest/api/3/issue")[-1]["fields"]
    assert epic_body["description"]["content"][0]["content"][0]["text"] == "Initiative:"


def test_create_task_is_a_sub_task_and_a_non_backlog_state_transitions():
    fake, _, story, _ = seeded()
    adapter, t = make(fake)
    task = adapter.create_item(WorkItem(Level.TASK, "Write The Test", parent=ItemRef(story["id"], Level.STORY),
                                        state=State.IN_PROGRESS))
    assert t.bodies("POST", "/rest/api/3/issue")[0]["fields"]["issuetype"] == {"id": fj.T_SUB}
    assert task.level is Level.TASK and task.parent.key == story["key"] and task.state is State.IN_PROGRESS
    assert t.bodies("POST", "/transitions") == [{"transition": {"id": f"t{fj.S_PROGRESS}"}}]


def test_the_tracker_refuses_a_task_straight_under_an_epic():
    fake, epic, _, _ = seeded()
    adapter, _ = make(fake)
    with pytest.raises(ValidationError, match="appropriate hierarchy"):
        adapter.create_item(WorkItem(Level.TASK, "Misplaced", parent=ItemRef(epic["key"])))


def test_create_refuses_bad_labels_members_components_before_writing():
    adapter, t = make()
    for item in (
        WorkItem(Level.STORY, "x", labels=("two words",)),
        WorkItem(Level.STORY, "x", assignees=("nobody",)),
        WorkItem(Level.STORY, "x", assignees=("Chris", "chris@example.invalid")),
        WorkItem(Level.STORY, "x", component="Nope"),
    ):
        with pytest.raises(ValidationError):
            adapter.create_item(item)
    assert t.bodies("POST", "") == []
    with pytest.raises(Unsupported, match="collapses"):
        adapter.create_item(WorkItem(Level.FEATURE, "A Feature"))


def test_a_just_created_item_is_found_while_the_search_lags():
    adapter, fake = make()
    made = adapter.create_item(WorkItem(Level.EPIC, "Lagging Epic", external_id="req-lag"))
    fake.hidden.add(made.id)  # /search/jql has not indexed it yet
    assert [i.id for i in adapter.find_items(external_id="req-lag")] == [made.id]
    other, _ = make(fake)  # a fresh process knows nothing it did not create
    assert other.find_items(external_id="req-lag") == []


def test_update_replaces_labels_but_keeps_the_xid_and_transitions_state():
    fake, _, story, _ = seeded()
    adapter, t = make(fake)
    after = adapter.update_item(story["key"], ItemPatch(labels=(), state=State.DONE, title="Renamed", assignees=()))
    put = t.bodies("PUT", f"/rest/api/3/issue/{story['key']}")[0]["fields"]
    assert put == {"summary": "Renamed", "assignee": None, "labels": ["xid:req-0001"]}
    assert after.labels == () and after.external_id == "req-0001" and after.state is State.DONE
    assert after.title == "Renamed" and after.assignees == ()
    with pytest.raises(ValidationError, match="empty"):
        adapter.update_item(story["key"], ItemPatch())
    with pytest.raises(Unsupported):
        adapter.update_item(story["key"], ItemPatch(feature=ItemRef("Intake")))


def test_add_comment_renders_adf_and_reads_the_author():
    fake, _, story, _ = seeded()
    adapter, t = make(fake)
    c = adapter.add_comment(Comment(ItemRef(story["id"], key=story["key"]), "Reviewed by **me**."))
    assert c.id and c.author == "Chris" and c.created_at.year == 2026
    body = t.bodies("POST", "/comment")[0]["body"]
    assert body["type"] == "doc" and body["content"][0]["content"][1]["marks"] == [{"type": "strong"}]


# --- iterations -------------------------------------------------------------------


def test_a_sprint_covering_today_starts_and_one_ahead_stays_planned():
    adapter, t = make()
    cur = adapter.create_iteration(Iteration("202609", start=date(2026, 9, 26), end=date(2026, 9, 27)))
    nxt = adapter.create_iteration(Iteration("202610", start=date(2026, 10, 1), end=date(2026, 10, 31)))
    assert (cur.state, cur.start, cur.end) == (IterationState.ACTIVE, date(2026, 9, 26), date(2026, 9, 27))
    assert (nxt.state, nxt.start, nxt.end) == (IterationState.PLANNED, date(2026, 10, 1), date(2026, 10, 31))
    created = t.bodies("POST", "/rest/agile/1.0/sprint")[0]
    assert created["startDate"] == "2026-09-26T00:00:00.000-04:00" and created["originBoardId"] == 2
    assert adapter.get_iteration("202610").id == nxt.id  # by name
    with pytest.raises(ValidationError, match="naming.iteration"):
        adapter.create_iteration(Iteration("Sprint 9"))


def test_starting_a_second_active_sprint_says_why():
    adapter, _ = make()
    adapter.create_iteration(Iteration("202609", start=date(2026, 9, 1), end=date(2026, 9, 30)))
    with pytest.raises(ValidationError, match="no parallel sprints"):
        adapter.create_iteration(Iteration("202608", start=date(2026, 9, 20), end=date(2026, 9, 28)))


def test_move_close_and_a_closed_sprint_refuses_items():
    fake, epic, story, _ = seeded()
    for s in fake.sprints.values():
        s["state"] = "closed"
    adapter, t = make(fake)
    cur = adapter.create_iteration(Iteration("202610", start=date(2026, 9, 27), end=date(2026, 10, 31)))
    adapter.move_to_iteration([story["key"], ItemRef(epic["id"], key=epic["key"])], "202610")
    assert t.bodies("POST", f"/sprint/{cur.id}/issue") == [{"issues": [story["key"], epic["key"]]}]
    assert adapter.get_item(story["key"]).iteration == cur.id
    closed = adapter.close_iteration("202610")
    assert closed.state is IterationState.CLOSED and adapter.close_iteration(cur.id or "").state is IterationState.CLOSED
    with pytest.raises(ValidationError, match="closed sprint"):
        adapter.move_to_iteration([story["key"]], cur.id or "")
    planned = adapter.create_iteration(Iteration("202611", start=date(2026, 11, 1), end=date(2026, 11, 30)))
    with pytest.raises(ValidationError, match="has not started"):
        adapter.close_iteration(planned.id or "")
    with pytest.raises(NotFound):
        adapter.get_iteration("209912")


def test_no_delete_anywhere():
    fake, epic, story, _ = seeded()
    adapter, t = make(fake)
    adapter.create_item(WorkItem(Level.STORY, "S", parent=ItemRef(epic["key"]), external_id="x"))
    adapter.update_item(story["key"], ItemPatch(labels=("bug",), state=State.CANCELLED))
    it = adapter.create_iteration(Iteration("202610", start=date(2026, 10, 1), end=date(2026, 10, 31)))
    adapter.move_to_iteration([story["key"]], it.id or "")
    assert "DELETE" not in {m for m, *_ in t.calls}
