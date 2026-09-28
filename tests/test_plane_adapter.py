"""Offline tests for the Plane adapter against the fake transport."""

from datetime import date

import pytest

from adapters.base import (
    AuthError,
    ConfigMismatch,
    ItemPatch,
    NotFound,
    TransportError,
    Unsupported,
    ValidationError,
)
from adapters.plane import PlaneAdapter
from server.config import BoardConfig
from server.model import (
    Comment,
    ItemRef,
    Iteration,
    IterationState,
    Level,
    Materialization,
    State,
    WorkItem,
)
from tests import fake_plane as fp

CONFIG = {
    "backend": "plane",
    "connection": {"token_env": "PLANE_API_KEY", "workspace": "ws", "project": "AA"},
    "levels": {
        "initiative": {"collapse": "label", "template": "initiative:{name}"},
        "epic": {"type": "Epic"},
        "feature": {"container": "module"},
        "story": {"type": fp.T_STORY},
        "bug": {"type": "Bug"},
        "task": {"type": "Task"},
    },
    "states": {"backlog": "Backlog", "todo": "Todo", "in_progress": "In Progress", "done": "Done", "cancelled": "Cancelled"},
    "labels": {"review": "needs-review", "taxonomy": ["bug", "feature"]},
    "naming": {"iteration": "YYYYMM"},
}


def make(routes=None, *, with_bug=True, config=None, today=date(2026, 9, 22)):
    transport = fp.FakeTransport(routes if routes is not None else fp.base_routes(with_bug=with_bug))
    cfg = BoardConfig.from_dict(config or CONFIG).check()
    return PlaneAdapter(cfg, transport, secret=lambda name: "unused", today=lambda: today), transport


# --- describe_board: the read-before-write gate --------------------------------


def test_describe_board_resolves_names_to_ids_and_fits():
    adapter, t = make()
    board = adapter.describe_board()
    assert board.problems == ()
    assert board.project_id == fp.PID and board.project_key == "AA"
    assert board.resolved == {
        Level.EPIC: fp.T_EPIC, Level.STORY: fp.T_STORY, Level.BUG: fp.T_BUG, Level.TASK: fp.T_TASK,
        Level.FEATURE: "module",
    }
    assert [s.name for s in board.states][2] == "In Progress"
    assert [m.name for m in board.members] == ["chris"]
    assert [c.name for c in board.iterations] == ["202608", "202609"]
    # describe is reads only, and the project was resolved from its identifier
    assert {m for m, *_ in t.calls} == {"GET"}
    assert adapter.capabilities.materializes(Level.FEATURE) and not adapter.capabilities.materializes(Level.INITIATIVE)


def test_describe_board_reports_every_mismatch_and_writes_refuse():
    cfg = {**CONFIG, "states": {**CONFIG["states"], "todo": "To Do"}, "labels": {"review": "review-me", "taxonomy": ["bug", "docs"]}}
    adapter, t = make(with_bug=False, config=cfg)
    board = adapter.describe_board()
    assert board.problems == (
        "levels.bug: no work-item type 'Bug' on the board (types: Epic, Story, Task)",
        "states.todo: no state named 'To Do' on the board (states: Backlog, Todo, In Progress, Done, Cancelled)",
        "labels.review: no label 'review-me' on the board (labels: needs-review, bug, feature, initiative:INIT-1)",
        "labels.taxonomy: not on the board: docs",
    )
    with pytest.raises(ConfigMismatch) as exc:
        adapter.create_item(WorkItem(Level.STORY, "x"))
    assert exc.value.problems == list(board.problems)
    assert t.bodies("POST", "") == []  # nothing was written
    # reads still work on a mismatched board
    assert adapter.get_item("AA-1").title == "Requester Intake"


def test_project_may_be_named_by_uuid_or_name():
    for ref in (fp.PID, "agentic_administration"):
        adapter, _ = make(config={**CONFIG, "connection": {**CONFIG["connection"], "project": ref}})
        assert adapter.describe_board().project_key == "AA"
    adapter, _ = make(config={**CONFIG, "connection": {**CONFIG["connection"], "project": "NOPE"}})
    with pytest.raises(NotFound):
        adapter.describe_board()


def test_feature_off_and_missing_container_kind():
    routes = fp.base_routes(with_bug=True)
    routes[f"GET {fp.PP}/features/"] = {"modules": False, "cycles": False}
    adapter, _ = make(routes)
    assert adapter.describe_board().problems == (
        "levels.feature: the Modules feature is off on this project",
        "the Cycles feature is off on this project (iterations need it)",
    )
    cfg = {**CONFIG, "levels": {**CONFIG["levels"], "feature": {"container": "component"}}}
    adapter, _ = make(config=cfg)
    assert "levels.feature: Plane's only container is 'module', not 'component'" in adapter.describe_board().problems


def test_vendor_errors_surface_as_the_taxonomy():
    adapter, t = make()
    t.fail[f"GET {fp.PP}/features/"] = AuthError("HTTP 403 on GET: Given API token is not valid")
    with pytest.raises(AuthError):
        adapter.describe_board()


# --- reads -----------------------------------------------------------------------


def test_read_maps_records_to_the_canonical_model():
    adapter, _ = make()
    story = adapter.get_item(fp.I_STORY)
    assert story.level is Level.STORY and story.key == "AA-2"
    assert story.parent == ItemRef(fp.I_EPIC)
    assert story.state is State.TODO
    assert story.labels == ("needs-review",)
    assert story.iteration == fp.C_202609
    assert story.feature == ItemRef(fp.M_INTAKE, Level.FEATURE)  # from min_module_name
    assert story.external_id == "req-0001"
    assert adapter.get_item("AA-1").level is Level.EPIC
    with pytest.raises(NotFound):
        adapter.get_item("AA-404")


def test_unknown_type_and_state_fall_back_to_is_epic_and_group():
    routes = fp.base_routes(with_bug=True)
    routes[f"GET {fp.PP}/work-item-types/"].append({"id": "aaaaaaaa-0000-0000-0000-00000000f00d", "name": "Odd", "is_epic": True})
    routes[f"GET {fp.PP}/states/"].append({"id": "bbbbbbbb-0000-0000-0000-00000000f00d", "name": "Review", "group": "started"})
    routes[f"GET {fp.PP}/work-items/"]["results"].append(
        fp.item_record("12121212-0000-0000-0000-00000000f00d", 3, "Odd One", "aaaaaaaa-0000-0000-0000-00000000f00d",
                       state="bbbbbbbb-0000-0000-0000-00000000f00d"))
    adapter, _ = make(routes)
    odd = adapter.get_item("AA-3")
    assert odd.level is Level.EPIC and odd.state is State.IN_PROGRESS


def test_find_items_lists_filters_and_searches():
    adapter, t = make()
    assert [i.key for i in adapter.find_items()] == ["AA-1", "AA-2"]
    assert [i.key for i in adapter.find_items(level=Level.STORY, state=State.TODO)] == ["AA-2"]
    assert adapter.find_items(state=State.DONE) == []
    # features are modules; initiatives are the workspace list
    assert [f.title for f in adapter.find_items(level=Level.FEATURE)] == ["Intake", "Adapter"]
    assert [f.id for f in adapter.find_items("ada", level=Level.FEATURE)] == [fp.M_ADAPTER]
    # external_id is the project list's lookup on both params: one record, or 404
    assert [h.key for h in adapter.find_items(external_id="req-0001")] == ["AA-2"]
    assert adapter.find_items(external_id="req-nope") == []
    assert adapter.find_items("nothing like it", external_id="req-0001") == []
    lookups = [p for m, path, p, _ in t.calls if path == f"{fp.PP}/work-items/" and p and "external_id" in p]
    assert lookups[0] == {"external_id": "req-0001", "external_source": "agentic_administration"}
    # free text is the workspace search, then hydrates by id
    t.routes[f"GET {fp.WS}/work-items/search/"] = lambda params, body: (
        {"issues": [{"id": fp.I_STORY, "project_id": fp.PID}]} if params == {"search": "file"} else {"issues": []}
    )
    assert [h.key for h in adapter.find_items("file")] == ["AA-2"]


def test_find_items_by_label_is_the_review_queue():
    adapter, _ = make()
    assert [i.key for i in adapter.find_items(label="needs-review")] == ["AA-2"]
    assert [i.key for i in adapter.find_items(label="Needs-Review")] == ["AA-2"]  # names ignore case
    assert adapter.find_items(label="bug") == []
    assert [i.key for i in adapter.find_items(iteration="202609", label="needs-review")] == ["AA-2"]
    assert adapter.find_items(state=State.BACKLOG, label="needs-review") == []  # AA-2 is todo


def test_an_ignored_external_id_filter_refuses_to_guess():
    adapter, t = make()
    t.external_id_lookup = False  # Plane answers the plain list instead of one record or 404
    with pytest.raises(TransportError, match="ignored the external_id filter"):
        adapter.find_items(external_id="req-0001")


# --- writes ----------------------------------------------------------------------


def test_create_story_under_epic_in_feature_with_everything():
    adapter, t = make()
    item = WorkItem(
        Level.STORY, "Requester Can Add A Comment",
        description="As a requester...\n\n- **Given** a story\n- When I comment",
        parent=ItemRef(fp.I_EPIC, Level.EPIC), feature=ItemRef(fp.M_INTAKE, Level.FEATURE),
        state=State.BACKLOG, assignees=("Chris",), labels=("needs-review", "feature"),
        iteration="202609", component="Adapter", external_id="req-0002",
    )
    created = adapter.create_item(item)
    body = t.bodies("POST", "/work-items/")[0]
    assert body == {
        "name": "Requester Can Add A Comment",
        "state": fp.S_BACKLOG,
        "type_id": fp.T_STORY,
        "parent": fp.I_EPIC,
        "description_html": "<p>As a requester...</p><ul><li><strong>Given</strong> a story</li><li>When I comment</li></ul>",
        "labels": [fp.L_REVIEW, fp.L_FEATURE],
        "assignees": [fp.U_CHRIS],
        "external_id": "req-0002",
        "external_source": "agentic_administration",
    }
    assert created.id and created.key == "AA-100" and created.level is Level.STORY
    assert created.feature == item.feature and created.component == "Adapter" and created.iteration == fp.C_202609
    memberships = [(p, b) for m, p, _, b in t.calls if m == "POST" and "-issues/" in p]
    assert memberships == [
        (f"{fp.PP}/modules/{fp.M_INTAKE}/module-issues/", {"issues": [created.id]}),
        (f"{fp.PP}/modules/{fp.M_ADAPTER}/module-issues/", {"issues": [created.id]}),
        (f"{fp.PP}/cycles/{fp.C_202609}/cycle-issues/", {"issues": [created.id]}),
    ]


def test_create_epic_collapses_its_initiative_into_a_label():
    adapter, t = make()
    epic = adapter.create_item(WorkItem(Level.EPIC, "Intake", initiative=ItemRef("i-1", Level.INITIATIVE, "INIT-1")))
    assert t.bodies("POST", "/work-items/")[0]["labels"] == [fp.L_INIT]
    assert epic.level is Level.EPIC and epic.labels == ("initiative:INIT-1",)


def test_create_with_description_line_collapse_prepends_the_line():
    cfg = {**CONFIG, "levels": {**CONFIG["levels"], "initiative": {"collapse": "description_line", "template": "**Initiative:** {name}"}}}
    adapter, t = make(config=cfg)
    adapter.create_item(WorkItem(Level.EPIC, "Intake", description="Body.", initiative=ItemRef("i-1", key="INIT-1")))
    assert t.bodies("POST", "/work-items/")[0]["description_html"] == "<p><strong>Initiative:</strong> INIT-1<br>Body.</p>"


def test_create_feature_is_a_module_and_rejects_a_parent():
    adapter, t = make()
    feature = adapter.create_item(WorkItem(Level.FEATURE, "Rollover", description="Sprint rollover."))
    assert feature.level is Level.FEATURE and feature.id
    assert t.bodies("POST", "/modules/")[0] == {"name": "Rollover", "project_id": fp.PID, "description": "Sprint rollover."}
    # the new module is usable right away
    adapter.create_item(WorkItem(Level.STORY, "S", feature=ItemRef("Rollover")))
    with pytest.raises(Unsupported):
        adapter.create_item(WorkItem(Level.FEATURE, "F", parent=ItemRef(fp.I_EPIC, Level.EPIC)))
    with pytest.raises(Unsupported):
        adapter.create_item(WorkItem(Level.INITIATIVE, "I"))


def test_create_refuses_unknown_label_member_module_before_writing():
    adapter, t = make()
    for item, fragment in (
        (WorkItem(Level.STORY, "S", labels=("nope",)), "no label 'nope'"),
        (WorkItem(Level.STORY, "S", assignees=("nobody",)), "no member 'nobody'"),
        (WorkItem(Level.STORY, "S", component="nowhere"), "no module 'nowhere'"),
    ):
        with pytest.raises(ValidationError, match=fragment):
            adapter.create_item(item)
    with pytest.raises(NotFound, match="no iteration '202612'"):
        adapter.create_item(WorkItem(Level.STORY, "S", iteration="202612"))
    assert t.bodies("POST", "/work-items/") == []


def test_invalid_item_is_rejected_by_the_model_first():
    adapter, t = make()
    with pytest.raises(ValueError, match="must have a parent"):
        adapter.create_item(WorkItem(Level.TASK, "orphan"))
    assert t.calls == []


def test_hierarchy_rejection_is_a_validation_error():
    adapter, t = make()
    t.fail[f"POST {fp.PP}/work-items/"] = ValidationError("HTTP 400 on POST: parent: Task cannot be a child of Epic")
    with pytest.raises(ValidationError, match="child of Epic"):
        adapter.create_item(WorkItem(Level.TASK, "T", parent=ItemRef(fp.I_EPIC)))


def test_update_item_patches_only_what_changed():
    adapter, t = make()
    updated = adapter.update_item("AA-2", ItemPatch(state=State.IN_PROGRESS, labels=()))
    assert t.bodies("PATCH", "/work-items/")[0] == {"state": fp.S_PROGRESS, "labels": []}
    assert updated.state is State.IN_PROGRESS and updated.labels == ()
    with pytest.raises(ValidationError, match="empty"):
        adapter.update_item("AA-2", ItemPatch())
    moved = adapter.update_item(fp.I_STORY, ItemPatch(feature=ItemRef(fp.M_ADAPTER)))
    assert moved.feature == ItemRef(fp.M_ADAPTER)
    assert t.calls[-1][1] == f"{fp.PP}/modules/{fp.M_ADAPTER}/module-issues/"
    assert not any(m == "DELETE" for m, *_ in t.calls)


def test_add_comment_renders_markdown():
    adapter, t = make()
    c = adapter.add_comment(Comment(ItemRef(fp.I_STORY), "Looks *good*."))
    assert t.bodies("POST", "/comments/")[0] == {"comment_html": "<p>Looks <em>good</em>.</p>"}
    assert c.id and c.author == "chris" and c.created_at.year == 2026


def test_iterations_create_move_close():
    adapter, t = make()
    with pytest.raises(ValidationError, match="naming.iteration"):
        adapter.create_iteration(Iteration("Sprint 1"))
    it = adapter.create_iteration(Iteration("202610", start=date(2026, 10, 1), end=date(2026, 10, 31)))
    assert t.bodies("POST", "/cycles/")[0] == {"name": "202610", "project_id": fp.PID, "start_date": "2026-10-01", "end_date": "2026-10-31"}
    assert it.id and it.state is IterationState.PLANNED
    adapter.move_to_iteration(["AA-1", ItemRef(fp.I_STORY)], "202610")
    assert t.calls[-1][3] == {"issues": [fp.I_EPIC, fp.I_STORY]}
    with pytest.raises(ValidationError, match="not started"):
        adapter.close_iteration("202610")
    closed = adapter.close_iteration("202609")
    assert t.bodies("PATCH", "/cycles/")[0] == {"end_date": "2026-09-21"}
    assert closed.state is IterationState.CLOSED
    assert adapter.close_iteration("202608").state is IterationState.CLOSED  # already closed: no PATCH
    assert len(t.bodies("PATCH", "/cycles/")) == 1


def test_label_materialized_level_round_trips_and_keeps_its_marker():
    cfg = {**CONFIG, "levels": {**CONFIG["levels"], "bug": {"label": "bug"}}}
    adapter, t = make(config=cfg)
    bug = adapter.create_item(WorkItem(Level.BUG, "Crash On Save", labels=("needs-review",)))
    body = t.bodies("POST", "/work-items/")[0]
    assert "type_id" not in body and body["labels"] == [fp.L_REVIEW, fp.L_BUG]
    assert bug.level is Level.BUG and bug.labels == ("needs-review", "bug")
    assert [i.key for i in adapter.find_items(level=Level.BUG)] == [bug.key]
    # the PO clears the review marker; the level marker stays
    cleared = adapter.update_item(bug.id, ItemPatch(labels=()))
    assert t.bodies("PATCH", "/work-items/")[0] == {"labels": [fp.L_BUG]}
    assert cleared.level is Level.BUG and cleared.labels == ("bug",)


def test_bad_collapse_template_is_a_config_problem():
    cfg = {**CONFIG, "levels": {**CONFIG["levels"], "initiative": {"collapse": "label", "template": "{title}"}}}
    adapter, _ = make(config=cfg)
    assert any(p.startswith("levels.initiative.template: only {name}") for p in adapter.describe_board().problems)


def test_close_iteration_that_started_today_is_refused_before_writing():
    routes = fp.base_routes(with_bug=True)
    routes[f"GET {fp.PP}/cycles/"].append({"id": fp.C_202609.replace("9", "7"), "name": "202611", "start_date": "2026-09-22", "end_date": "2026-11-30", "status": "current"})
    adapter, t = make(routes)
    with pytest.raises(ValidationError, match="started today"):
        adapter.close_iteration("202611")
    assert t.bodies("PATCH", "/cycles/") == []


def test_unresolved_secret_is_an_auth_error():
    from adapters.plane.transport import PlaneTransport
    from server.secrets import SecretUnavailable

    def missing():
        raise SecretUnavailable("PLANE_API_KEY is not set")

    with pytest.raises(AuthError, match="PLANE_API_KEY is not set"):
        PlaneTransport(missing, sleep=lambda s: None).request("GET", "/x")


def test_provision_bug_type_then_config_fits():
    adapter, t = make(with_bug=False)
    assert "levels.bug: no work-item type 'Bug' on the board (types: Epic, Story, Task)" in adapter.describe_board().problems
    created = adapter.provision_work_item_type("Bug")
    assert t.bodies("POST", "/work-item-types/")[0] == {"name": "Bug"}
    assert created.name == "Bug"
    assert adapter.describe_board().problems == ()
    assert adapter.provision_work_item_type("bug") == created  # idempotent by name
    assert len(t.bodies("POST", "/work-item-types/")) == 1


def test_provision_creates_only_the_missing_types_and_labels():
    adapter, t = make(with_bug=False)
    board = adapter.provision(types=["Bug", "Story"], labels=["needs-review", "docs", "Docs"])
    assert t.bodies("POST", "/work-item-types/") == [{"name": "Bug"}]
    assert t.bodies("POST", "/labels/") == [{"name": "docs"}]
    assert "docs" in [l.name for l in board.labels] and board.problems == ()
    n = len(t.calls)
    assert adapter.provision(types=["bug"], labels=["DOCS"]) == board  # idempotent, and no re-read
    assert len(t.calls) == n


def test_set_features_patches_then_reports_the_re_read():
    routes = fp.base_routes(with_bug=True)
    routes[f"GET {fp.PP}/features/"]["epics"] = False
    adapter, t = make(routes)
    t.features_patchable = False  # Plane answers the PATCH but changes nothing
    assert adapter.set_features(epics=True)["epics"] is False
    assert t.bodies("PATCH", "/features/") == [{"epics": True}]
    t.features_patchable = True
    assert adapter.set_features(epics=True)["epics"] is True


def test_get_iteration_reads_the_live_status_by_name_or_id():
    adapter, _ = make()
    assert adapter.get_iteration("202608").state is IterationState.CLOSED
    assert adapter.get_iteration(fp.C_202609).state is IterationState.ACTIVE
    with pytest.raises(NotFound, match="no iteration '202612'"):
        adapter.get_iteration("202612")


def test_find_items_in_an_iteration_reads_the_cycle_membership():
    adapter, t = make()
    got = adapter.find_items(iteration="202609")
    assert [(i.key, i.iteration) for i in got] == [("AA-2", fp.C_202609)]
    assert (f"GET", f"{fp.PP}/cycles/{fp.C_202609}/cycle-issues/") in t.log
    assert adapter.find_items(iteration="202609", state=State.DONE) == []
    assert adapter.find_items("nothing like it", iteration="202609") == []
    assert adapter.find_items(iteration="202608") == []
    # modules and initiatives never sit in a cycle
    assert adapter.find_items(level=Level.FEATURE, iteration="202609") == []
    assert adapter.find_items(level=Level.INITIATIVE, iteration="202609") == []
    # an external_id lookup narrowed to the wrong iteration finds nothing
    assert [i.key for i in adapter.find_items(external_id="req-0001", iteration=fp.C_202609)] == ["AA-2"]
    assert adapter.find_items(external_id="req-0001", iteration="202608") == []
    with pytest.raises(NotFound):
        adapter.find_items(iteration="202612")


def test_create_iteration_finds_one_of_that_name_instead_of_duplicating():
    adapter, t = make()
    again = adapter.create_iteration(Iteration("202609", start=date(2026, 9, 1), end=date(2026, 9, 30)))
    assert again.id == fp.C_202609 and again.state is IterationState.ACTIVE
    assert adapter.create_iteration(Iteration("202609")).id == fp.C_202609  # no dates: take it as it is
    with pytest.raises(ValidationError, match="already exists, dated 2026-09-01–2026-09-30"):
        adapter.create_iteration(Iteration("202609", start=date(2026, 9, 2), end=date(2026, 9, 30)))
    assert t.bodies("POST", "/cycles/") == []


def test_provision_cut_short_never_writes_the_same_thing_twice():
    from adapters.base import RateLimited

    adapter, t = make(with_bug=False)
    t.fail[f"POST {fp.PP}/labels/"] = RateLimited("rate limited on POST labels/")
    with pytest.raises(RateLimited):
        adapter.provision(types=["Bug"], labels=["docs"])
    del t.fail[f"POST {fp.PP}/labels/"]
    adapter.provision(types=["Bug"], labels=["docs"])  # the retry re-reads the board first
    assert t.bodies("POST", "/work-item-types/") == [{"name": "Bug"}]
    assert adapter.describe_board().problems == ()
