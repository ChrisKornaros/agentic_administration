"""Offline tests for the board config. Nothing here touches a tracker."""

import copy
from pathlib import Path

import pytest

from server.config import (
    Backend,
    BoardConfig,
    BoardType,
    Confirm,
    InvalidBoardConfig,
    ItemCase,
    Naming,
    load,
)
from server.model import (
    Capabilities,
    CollapseTarget,
    DescriptionFormat,
    Level,
    Materialization,
    State,
    to_jsonable,
)

BOARDS = Path(__file__).resolve().parents[1] / "examples" / "boards"
EXAMPLE = BOARDS / "plane.example.toml"
CALENDAR_EXAMPLE = BOARDS / "calendar.example.toml"

PLANE = {
    "backend": "plane",
    "connection": {"token_env": "PLANE_API_KEY", "workspace": "ws", "project": "p-uuid"},
    "levels": {
        "initiative": {"collapse": "label", "template": "initiative:{name}"},
        "epic": {"type": "t-epic"},
        "feature": {"container": "module"},
        "story": {"type": "t-story"},
        "bug": {"type": "t-bug"},
        "task": {"type": "t-task"},
    },
    "states": {
        "backlog": "Backlog", "todo": "Todo", "in_progress": "In Progress",
        "done": "Done", "cancelled": "Cancelled",
    },
    "labels": {"review": "needs-review", "taxonomy": ["bug", "feature"]},
}


def variant(**changes) -> dict:
    """PLANE with top-level sections replaced (deep-copied first)."""
    data = copy.deepcopy(PLANE)
    data.update(changes)
    return data


def problems_of(data: dict) -> list[str]:
    try:
        return BoardConfig.from_dict(data).validate()
    except InvalidBoardConfig as exc:
        return exc.problems


# --- the example file ---------------------------------------------------------


def test_example_loads_and_exports():
    cfg = load(EXAMPLE)
    assert cfg.backend is Backend.PLANE and cfg.confirm is Confirm.ALWAYS
    assert cfg.connection.token_env == "PLANE_API_KEY"
    assert cfg.levels[Level.FEATURE].how is Materialization.CONTAINER
    assert cfg.levels[Level.INITIATIVE].collapse.target is CollapseTarget.DESCRIPTION_LINE
    assert cfg.states[State.IN_PROGRESS] == "In Progress"
    assert cfg.labels.review == "needs-review"
    assert cfg.naming.item_case is ItemCase.TITLE
    wire = to_jsonable(cfg)
    assert wire["levels"]["epic"] == {"how": "type", "ref": wire["levels"]["epic"]["ref"], "collapse": None}
    assert wire["states"]["done"] == "Done"


def test_example_feeds_capabilities_directly():
    cfg = load(EXAMPLE)
    caps = Capabilities(
        "plane", cfg.materializations(), DescriptionFormat.HTML,
        states_via_transitions=False, native_idempotency_key=True,
        collapse=cfg.collapse_rules(),
    )
    assert not caps.materializes(Level.INITIATIVE) and caps.materializes(Level.TASK)


@pytest.mark.parametrize("path", sorted(BOARDS.glob("*.example.toml")), ids=lambda p: p.name)
def test_every_example_board_loads_and_checks(path):
    assert load(path).validate() == []


def test_the_calendar_example_has_no_bug_level_and_review_off():
    cfg = load(CALENDAR_EXAMPLE)
    assert cfg.board_type is BoardType.CALENDAR and cfg.backend is Backend.PLANE
    assert Level.BUG not in cfg.levels and cfg.labels.review is None
    caps = Capabilities(
        "plane", cfg.materializations(), DescriptionFormat.HTML,
        states_via_transitions=False, native_idempotency_key=True,
        collapse=cfg.collapse_rules(),
    )
    assert caps.levels[Level.BUG] is Materialization.ABSENT and not caps.materializes(Level.BUG)
    assert caps.materializes(Level.STORY) and caps.levels[Level.FEATURE] is Materialization.CONTAINER
    assert cfg.fields == {"published": "Published", "channels": "Channels"}  # D41


# --- defaults and shape ------------------------------------------------------


def test_minimal_dict_gets_defaults():
    cfg = BoardConfig.from_dict(PLANE).check()
    assert cfg.confirm is Confirm.ALWAYS and cfg.board_type is BoardType.SOFTWARE
    assert cfg.naming == Naming()
    assert cfg.connection.base_url is None
    assert cfg.connection.ids == {"workspace": "ws", "project": "p-uuid"}


def test_unknown_and_missing_sections_are_reported_together():
    data = variant(extra={})
    del data["states"]
    with pytest.raises(InvalidBoardConfig) as exc:
        BoardConfig.from_dict(data)
    assert exc.value.problems == ["unknown top-level keys: extra", "missing section: states"]


def test_bad_enum_values():
    p = problems_of(variant(backend="trello", confirm="sometimes", board_type="kanban"))
    assert any("backend: 'trello' is not one of plane, jira, generic" in x for x in p)
    assert any("confirm: 'sometimes' is not one of always, never" in x for x in p)
    assert "board_type: 'kanban' is not one of software, calendar" in p


# --- secrets stay out of the file --------------------------------------------


@pytest.mark.parametrize("token_env", ["plane_api_abc123.def456", "PLANE API KEY", ""])
def test_token_env_must_be_a_variable_name(token_env):
    data = variant(connection={**PLANE["connection"], "token_env": token_env})
    assert any("must be the *name* of an environment variable" in p for p in problems_of(data))


@pytest.mark.parametrize("key", ["api_key", "token", "password", "client_secret"])
def test_credential_looking_connection_keys_are_rejected(key):
    data = variant(connection={**PLANE["connection"], key: "x"})
    assert any(f"connection.{key} looks like a credential" in p for p in problems_of(data))


# --- connection per backend ------------------------------------------------


@pytest.mark.parametrize(
    "backend, missing",
    [
        ("plane", "project, workspace"),
        ("jira", "board_id, project_key, site"),
    ],
)
def test_backend_specific_connection_keys(backend, missing):
    data = variant(backend=backend, connection={"token_env": "T"})
    assert f"connection for {backend} needs: {missing}" in problems_of(data)
    assert "connection for generic needs" not in " ".join(
        problems_of(variant(backend="generic", connection={"token_env": "T"}))
    )


def test_jira_connection_accepts_numeric_board_id():
    data = variant(
        backend="jira",
        connection={"token_env": "JIRA_TOKEN", "user_env": "JIRA_USER", "site": "x.atlassian.net",
                    "project_key": "AA", "board_id": 42},
    )
    cfg = BoardConfig.from_dict(data).check()
    assert cfg.connection.ids["board_id"] == "42" and cfg.connection.user_env == "JIRA_USER"
    assert "user_env" not in cfg.connection.ids


def test_jira_needs_user_env_and_it_must_be_a_name():
    conn = {"token_env": "JIRA_TOKEN", "site": "x.atlassian.net", "project_key": "AA", "board_id": 42}
    assert "connection for jira needs user_env (the env var holding the account email)" in problems_of(
        variant(backend="jira", connection=conn))
    assert any("connection.user_env must be the *name*" in p for p in problems_of(
        variant(backend="jira", connection={**conn, "user_env": "me@example.invalid"})))


# --- levels ------------------------------------------------------------------


def test_every_level_must_be_declared():
    levels = {k: v for k, v in PLANE["levels"].items() if k not in ("bug", "feature")}
    assert "levels missing: bug, feature" in problems_of(variant(levels=levels))


@pytest.mark.parametrize("level", ["epic", "story", "bug", "task"])
def test_core_levels_cannot_collapse(level):
    levels = {**PLANE["levels"], level: {"collapse": "label"}}
    assert f"levels.{level} is a core level and cannot collapse" in problems_of(variant(levels=levels))


def test_optional_levels_may_collapse_anywhere():
    levels = {
        **PLANE["levels"],
        "feature": {"collapse": "description_line", "template": "**Feature:** {name}"},
    }
    cfg = BoardConfig.from_dict(variant(levels=levels)).check()
    assert cfg.levels[Level.FEATURE].collapse.template == "**Feature:** {name}"
    assert set(cfg.collapse_rules()) == {Level.INITIATIVE, Level.FEATURE}


def test_level_needs_exactly_one_form():
    levels = {**PLANE["levels"], "epic": {"type": "a", "label": "b"}, "story": {}}
    p = problems_of(variant(levels=levels))
    assert "levels.epic: give exactly one of type, container, parent, label, collapse" in p
    assert "levels.story: give exactly one of type, container, parent, label, collapse" in p


def test_level_form_details():
    # shape problems come from from_dict; the empty-target rule from validate()
    assert "levels.epic (type) needs a non-empty target" in problems_of(
        variant(levels={**PLANE["levels"], "epic": {"type": ""}})
    )
    levels = {
        **PLANE["levels"],
        "story": {"type": "s", "template": "x"},
        "bug": {"collapse": "sideways"},
        "task": {"type": "t", "colour": "red"},
        "sprint": {"type": "x"},
    }
    p = problems_of(variant(levels=levels))
    assert "levels.story: template only applies to collapse" in p
    assert any("levels.bug.collapse: 'sideways' is not one of" in x for x in p)
    assert "levels.task: unknown keys colour" in p
    assert "levels.sprint: unknown level" in p


def test_generic_parent_only_mode():
    levels = {
        "initiative": {"collapse": "label"},
        "epic": {"parent": "type:epic"},
        "feature": {"parent": "type:feature"},
        "story": {"parent": "type:story"},
        "bug": {"parent": "type:bug"},
        "task": {"parent": "type:task"},
    }
    cfg = BoardConfig.from_dict(variant(backend="generic", connection={"token_env": "T"}, levels=levels)).check()
    assert cfg.materializations()[Level.STORY] is Materialization.PARENT
    assert cfg.levels[Level.STORY].ref == "type:story"


# --- states and labels ---------------------------------------------------------


def test_states_must_cover_the_canonical_five():
    p = problems_of(variant(states={"backlog": "Backlog", "done": "Done", "todo": ""}))
    assert "states missing: cancelled, in_progress" in p
    assert "states mapped to an empty name: todo" in p
    assert "states.weird: unknown canonical state" in problems_of(
        variant(states={**PLANE["states"], "weird": "x"})
    )


def test_review_label_is_required():
    assert "labels.review is required (the review marker, e.g. needs-review)" in problems_of(variant(labels={}))
    assert "labels.review is empty (the review marker is required)" in problems_of(variant(labels={"review": " "}))
    assert "labels: unknown keys colour" in problems_of(variant(labels={"review": "r", "colour": "x"}))
    assert "labels.review must be a string (the review marker, e.g. needs-review)" in problems_of(
        variant(labels={"review": True}))
    no_labels = variant()
    del no_labels["labels"]
    assert problems_of(no_labels) == ["labels.review is required (the review marker, e.g. needs-review)"]


# --- board types (D38–D40) -------------------------------------------------------


def without_bug() -> dict:
    return {k: v for k, v in PLANE["levels"].items() if k != "bug"}


def test_a_calendar_board_may_leave_out_bug_and_the_review_label():
    data = variant(board_type="calendar", levels=without_bug())
    del data["labels"]
    cfg = BoardConfig.from_dict(data).check()
    assert cfg.labels.review is None and cfg.labels.taxonomy == ()
    assert cfg.materializations()[Level.BUG] is Materialization.ABSENT
    # giving the label turns review on; Bug may still be mapped
    cfg = BoardConfig.from_dict(variant(board_type="calendar")).check()
    assert cfg.labels.review == "needs-review" and cfg.levels[Level.BUG].how is Materialization.TYPE


def test_a_calendar_board_still_needs_the_other_levels_and_a_real_label():
    levels = {k: v for k, v in without_bug().items() if k != "story"}
    p = problems_of(variant(board_type="calendar", levels=levels, labels={"review": " "}))
    assert p == ["levels missing: story", "labels.review is empty (leave it out to turn review off)"]


def test_a_software_board_still_requires_bug_and_the_review_label():
    p = problems_of(variant(levels=without_bug(), labels={"taxonomy": []}))
    assert p == ["levels missing: bug", "labels.review is required (the review marker, e.g. needs-review)"]


# --- naming --------------------------------------------------------------------


def test_iteration_pattern():
    assert Naming().iteration_name_ok("202609")
    assert not Naming().iteration_name_ok("2026-09")
    sprint = Naming(iteration="Sprint YYYY-MM-DD")
    assert sprint.iteration_name_ok("Sprint 2026-09-22") and not sprint.iteration_name_ok("Sprint 2026")
    p = problems_of(variant(naming={"iteration": "", "item_case": "shouting", "x": 1}))
    assert "naming.iteration must be a non-empty pattern" in p
    assert any("naming.item_case: 'shouting' is not one of title, sentence, any" in x for x in p)
    assert "naming: unknown keys x" in p


def test_check_raises_with_every_problem():
    data = variant(labels={"review": ""}, states={})
    with pytest.raises(InvalidBoardConfig) as exc:
        BoardConfig.from_dict(data).check()
    assert exc.value.problems == [
        "states missing: backlog, cancelled, done, in_progress, todo",
        "labels.review is empty (the review marker is required)",
    ]


# --- custom fields (D41) ---------------------------------------------------------


def test_fields_map_a_name_to_the_trackers_property_or_field():
    cfg = BoardConfig.from_dict(variant(fields={"published": "Published", "points": "customfield_10037"})).check()
    assert cfg.fields == {"published": "Published", "points": "customfield_10037"}
    assert BoardConfig.from_dict(PLANE).fields == {}
    p = problems_of(variant(fields={"published": "", "points": 3}))
    assert p == ["fields.published must name the tracker's property or field (its name or id)",
                 "fields.points must name the tracker's property or field (its name or id)"]
    assert problems_of(variant(fields=["Published"])) == ["fields must be a table"]
