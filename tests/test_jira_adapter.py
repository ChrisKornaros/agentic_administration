"""Offline tests for the Jira adapter against the fake transport."""

from datetime import date

import pytest

from adapters.base import AuthError, ConfigMismatch, ItemPatch, NotFound, Unsupported, ValidationError
from adapters.jira import JiraAdapter
from adapters.jira.transport import JiraTransport
from server.config import BoardConfig
from server.model import Comment, ItemRef, Iteration, IterationState, Level, Materialization, State, WorkItem
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


# D38–D40: no Bug level and review off
CALENDAR = {**CONFIG, "board_type": "calendar", "labels": {"taxonomy": ["feature"]},
            "levels": {k: v for k, v in CONFIG["levels"].items() if k != "bug"}}


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


def test_a_calendar_board_needs_no_bug_type_or_review_label():
    adapter, t = make(config=CALENDAR)
    board = adapter.describe_board()
    assert board.problems == () and Level.BUG not in board.resolved
    assert {l.name for l in board.labels} == {"bug", "docs", "feature"}  # no review label is declared
    assert adapter.capabilities.levels[Level.BUG] is Materialization.ABSENT
    searches = len(t.calls)
    assert adapter.find_items(level=Level.BUG) == [] and len(t.calls) == searches  # not even a search
    with pytest.raises(Unsupported, match="this board has no bug level"):
        adapter.create_item(WorkItem(Level.BUG, "Crash On Save"))
    story = adapter.create_item(WorkItem(Level.STORY, "Loaves Of The Week", external_id="cal-1"))
    assert story.labels == () and t.bodies("POST", "/rest/api/3/issue")[0]["fields"]["labels"] == ["xid:cal-1"]


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


def test_find_items_by_label_is_the_review_queue():
    fake, _, story, _ = seeded()
    adapter, t = make(fake)
    assert [i.key for i in adapter.find_items(label="needs-review")] == [story["key"]]
    assert t.calls[-1][2]["jql"] == 'project = "AA" AND labels = "needs-review" ORDER BY created DESC'
    assert adapter.find_items(label="bug") == []
    assert [i.key for i in adapter.find_items(iteration="202609", label="needs-review")] == [story["key"]]


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


def test_jira_takes_a_sub_task_under_an_epic_so_the_model_is_the_guard():
    fake, epic, story, _ = seeded()
    adapter, _ = make(fake)
    # live Jira accepted this (AGADM-5, 2026-09-27): only the model refuses it, when it knows the level
    made = adapter.create_item(WorkItem(Level.TASK, "Misplaced", parent=ItemRef(epic["key"])))
    assert made.level is Level.TASK and made.parent.level is Level.EPIC
    # a parent below its child is still refused (the model never asks: an epic has no parent)
    with pytest.raises(ValidationError, match="appropriate hierarchy"):
        fake.request("POST", "/rest/api/3/issue", body={"fields": {
            "summary": "x", "issuetype": {"id": fj.T_EPIC}, "parent": {"key": story["key"]}}})


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


def test_a_sprint_made_ahead_is_found_and_started_on_its_first_day():
    fake = fj.FakeJira()
    adapter, t = make(fake)
    ahead = adapter.create_iteration(Iteration("202610", start=date(2026, 10, 1), end=date(2026, 10, 31)))
    assert ahead.state is IterationState.PLANNED
    later, _ = make(fake, today=date(2026, 10, 1))
    started = later.create_iteration(Iteration("202610", start=date(2026, 10, 1), end=date(2026, 10, 31)))
    assert started.id == ahead.id and started.state is IterationState.ACTIVE
    assert later.create_iteration(Iteration("202610")).state is IterationState.ACTIVE  # again: nothing to do
    assert [b["name"] for b in t.bodies("POST", "/rest/agile/1.0/sprint") if "name" in b] == ["202610"]  # no duplicate
    assert t.bodies("POST", f"/rest/agile/1.0/sprint/{ahead.id}") == [{"state": "active"}]
    with pytest.raises(ValidationError, match="already exists, dated 2026-10-01–2026-10-31"):
        later.create_iteration(Iteration("202610", start=date(2026, 10, 2), end=date(2026, 10, 31)))


def test_a_found_sprint_that_cannot_start_says_why():
    fake = fj.FakeJira()
    fake.add_sprint("202609", "active", "2026-09-01T00:00:00-04:00", "2026-10-02T23:59:00-04:00")
    fake.add_sprint("202610", "future", "2026-10-01T00:00:00-04:00", "2026-10-31T23:59:00-04:00")
    adapter, _ = make(fake, today=date(2026, 10, 1))
    with pytest.raises(ValidationError, match="found sprint '202610' but Jira would not start it"):
        adapter.create_iteration(Iteration("202610"))


def test_find_items_in_a_sprint_keeps_the_issues_it_holds_now():
    fake, epic, story, sprint = seeded()
    adapter, t = make(fake)
    assert [i.key for i in adapter.find_items(iteration="202609")] == [story["key"]]
    assert 'sprint = ' + str(sprint["id"]) in t.calls[-1][2]["jql"]
    # carried out of a closed sprint, the issue keeps it in its history but is no longer in it
    fake.sprints[str(sprint["id"])]["state"] = "closed"
    nxt = adapter.create_iteration(Iteration("202610", start=date(2026, 10, 1), end=date(2026, 10, 31)))
    adapter.move_to_iteration([story["key"]], "202610")
    assert adapter.find_items(iteration="202609") == []
    assert [(i.key, i.iteration) for i in adapter.find_items(iteration="202610")] == [(story["key"], nxt.id)]
    with pytest.raises(NotFound):
        adapter.find_items(iteration="Sprint 12")
    with pytest.raises(NotFound):  # a YYYYMM name is all digits, so it also reads as a sprint id
        adapter.find_items(iteration="202611")


def test_a_small_limit_still_finds_what_a_closed_sprint_holds_under_its_history():
    fake = fj.FakeJira()
    old = fake.add_sprint("202609", "closed", "2026-09-01T00:00:00-04:00", "2026-09-30T23:59:00-04:00")
    nxt = fake.add_sprint("202610", "future", "2026-10-01T00:00:00-04:00", "2026-10-31T23:59:00-04:00")
    left = fake.add_issue(fj.T_STORY, "Still In The Old Sprint", **{fj.SPRINT_FIELD: [old]})
    for n in range(3):  # newer issues carried out of 202609: `sprint =` matches them first
        fake.add_issue(fj.T_STORY, f"Rolled {n}", **{fj.SPRINT_FIELD: [old, nxt]})
    adapter, _ = make(fake)
    assert [i.key for i in adapter.find_items(iteration="202609", limit=1)] == [left["key"]]


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
    with pytest.raises(ValidationError, match="has not been completed"):
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


# --- dates and custom fields (D41) -----------------------------------------------------

FIELDS = {**CONFIG, "fields": {"channels": "Channels"}}


def test_describe_finds_the_start_date_by_name_and_reads_screens_only_with_fields():
    adapter, t = make()
    board = adapter.describe_board()
    assert board.features["start_date_field"] == fj.START_FIELD  # not Advanced Roadmaps' Target start
    assert board.fields == () and not [p for _, p in t.log if "createmeta" in p]
    fake = fj.FakeJira()
    fake.screen.add(fj.CHANNELS)
    adapter, t = make(fake, config=FIELDS)
    board = adapter.describe_board()
    assert board.problems == () and {m for m, *_ in t.calls} == {"GET"}
    assert len([p for _, p in t.log if "createmeta" in p]) == 4  # one per mapped type
    [channels] = board.fields
    assert (channels.kind.value, channels.multi, channels.options) == ("option", True, ("Web", "Email", "Print"))
    assert channels.levels == {lv: fj.CHANNELS for lv in (Level.EPIC, Level.STORY, Level.BUG, Level.TASK)}
    assert make(fake, config={**CONFIG, "fields": {"channels": fj.CHANNELS}})[0].describe_board().fields[0].name == "channels"


def test_a_field_off_the_screens_or_unknown_is_a_config_problem():
    adapter, _ = make(config={**CONFIG, "fields": {"channels": "Channels", "cost": "Cost"}})
    assert adapter.describe_board().problems == (
        "fields.cost: no field 'Cost' on the site (a new custom field is listed only once it is on one of "
        "the project's screens)",
        f"fields.channels: {fj.CHANNELS} (Channels) is on no mapped type's create screen; add it to the project's screens",
    )
    fake = fj.FakeJira()
    fake.fields.append({"id": "customfield_10099", "name": "Channels", "custom": True, "schema": {"type": "string"}})
    adapter, _ = make(fake, config=FIELDS)
    assert adapter.describe_board().problems == (
        f"fields.channels: 2 fields are named 'Channels' ({fj.CHANNELS}, customfield_10099); name one by its id",)


def test_dates_and_values_ride_in_the_create_and_read_back():
    fake, epic, _, _ = seeded()
    fake.screen.add(fj.CHANNELS)
    adapter, t = make(fake, config=FIELDS)
    made = adapter.create_item(WorkItem(
        Level.STORY, "Loaves Of The Week", parent=ItemRef(epic["key"], Level.EPIC),
        start_date=date(2026, 10, 1), target_date=date(2026, 10, 5), fields={"channels": ["web", "Print"]},
    ))
    body = t.bodies("POST", "/rest/api/3/issue")[0]["fields"]
    assert (body[fj.START_FIELD], body["duedate"]) == ("2026-10-01", "2026-10-05")
    assert body[fj.CHANNELS] == [{"value": "Web"}, {"value": "Print"}]  # the board's own option names
    assert (made.start_date, made.target_date) == (date(2026, 10, 1), date(2026, 10, 5))
    assert made.fields == {"channels": ["Web", "Print"]}
    [listed] = adapter.find_items(external_id=None, query="Loaves")
    assert listed.fields == made.fields and listed.target_date == date(2026, 10, 5)  # the search carries both
    after = adapter.update_item(made.key, ItemPatch(start_date=date(2026, 10, 2), fields={"channels": ["Email"]}))
    put = t.bodies("PUT", f"/rest/api/3/issue/{made.key}")[0]["fields"]
    assert put == {fj.START_FIELD: "2026-10-02", fj.CHANNELS: [{"value": "Email"}]}
    assert after.start_date == date(2026, 10, 2) and after.fields == {"channels": ["Email"]}


def test_bad_values_and_a_missing_start_date_field_refuse_before_writing():
    fake = fj.FakeJira()
    fake.screen.add(fj.CHANNELS)
    adapter, t = make(fake, config=FIELDS)
    with pytest.raises(ValidationError, match="takes a list of option names"):
        adapter.create_item(WorkItem(Level.STORY, "S", fields={"channels": ["Radio"]}))
    fake.fields = [f for f in fake.fields if f["id"] != fj.START_FIELD]
    adapter, _ = make(fake, config=FIELDS)
    with pytest.raises(ValidationError, match="no field named 'Start date'"):
        adapter.create_item(WorkItem(Level.STORY, "S", start_date=date(2026, 10, 1)))
    assert t.bodies("POST", "/rest/api/3/issue") == []
