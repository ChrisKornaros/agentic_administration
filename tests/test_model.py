"""Offline tests for the canonical model. Nothing here touches a tracker."""

import json
from datetime import date

import pytest

from server.model import (
    Capabilities,
    CollapseRule,
    CollapseTarget,
    DescriptionFormat,
    InvalidWorkItem,
    ItemRef,
    Iteration,
    IterationState,
    Level,
    Materialization,
    State,
    WorkItem,
    to_jsonable,
)

EPIC = ItemRef("e1", Level.EPIC, "AA-1")
STORY = ItemRef("s1", Level.STORY, "AA-2")
FEATURE = ItemRef("f1", Level.FEATURE)
INITIATIVE = ItemRef("i1", Level.INITIATIVE)


# --- placement rules -------------------------------------------------------


@pytest.mark.parametrize(
    "level, parent",
    [
        (Level.INITIATIVE, None),
        (Level.EPIC, None),
        (Level.FEATURE, None),
        (Level.FEATURE, EPIC),
        (Level.STORY, None),  # orphan stories are allowed
        (Level.STORY, EPIC),
        (Level.BUG, EPIC),
        (Level.TASK, STORY),
        (Level.TASK, ItemRef("b1", Level.BUG)),
        (Level.TASK, ItemRef("unknown")),  # parent level unknown: not checked
    ],
)
def test_valid_placements(level, parent):
    assert WorkItem(level, "t", parent=parent).validate() == []


@pytest.mark.parametrize(
    "level, parent, fragment",
    [
        (Level.TASK, None, "must have a parent"),
        (Level.EPIC, INITIATIVE, "never has a parent"),
        (Level.INITIATIVE, EPIC, "never has a parent"),
        (Level.STORY, STORY, "cannot be parented under a story"),
        (Level.STORY, FEATURE, "cannot be parented under a feature"),
        (Level.TASK, EPIC, "cannot be parented under a epic"),
        (Level.FEATURE, STORY, "cannot be parented under a story"),
    ],
)
def test_invalid_placements(level, parent, fragment):
    problems = WorkItem(level, "t", parent=parent).validate()
    assert len(problems) == 1 and fragment in problems[0]


def test_feature_attachment_only_on_story_and_bug():
    assert WorkItem(Level.STORY, "t", feature=FEATURE).validate() == []
    assert WorkItem(Level.BUG, "t", feature=FEATURE).validate() == []
    assert "cannot carry a feature" in WorkItem(Level.TASK, "t", parent=STORY, feature=FEATURE).validate()[0]
    assert "cannot carry a feature" in WorkItem(Level.EPIC, "t", feature=FEATURE).validate()[0]
    assert "feature ref points at a epic" in WorkItem(Level.STORY, "t", feature=EPIC).validate()[0]


def test_initiative_attachment_only_on_epic():
    assert WorkItem(Level.EPIC, "t", initiative=INITIATIVE).validate() == []
    assert "cannot carry an initiative" in WorkItem(Level.STORY, "t", initiative=INITIATIVE).validate()[0]
    assert "initiative ref points at a epic" in WorkItem(Level.EPIC, "t", initiative=EPIC).validate()[0]


def test_empty_title_and_check_raises_with_all_problems():
    item = WorkItem(Level.TASK, "   ")
    with pytest.raises(InvalidWorkItem) as exc:
        item.check()
    assert exc.value.problems == ["title is empty", "a task must have a parent (bug or story)"]
    assert WorkItem(Level.STORY, "ok").check().title == "ok"


def test_defaults_land_in_backlog_with_no_delete_state():
    assert WorkItem(Level.STORY, "t").state is State.BACKLOG
    assert {s.value for s in State} == {"backlog", "todo", "in_progress", "done", "cancelled"}


# --- export / import -------------------------------------------------------


def test_work_item_round_trips_through_json():
    item = WorkItem(
        Level.STORY,
        "Requester can file a bug",
        description="As a requester...\n\n**Given** ...",
        id="s9",
        key="AA-9",
        parent=EPIC,
        feature=FEATURE,
        state=State.TODO,
        assignees=("chris",),
        labels=("needs-review",),
        iteration="cyc-202609",
        component="intake",
        external_id="req-0001",
        related=(STORY,),
        links=("https://example.invalid/req/1",),
    )
    wire = json.loads(json.dumps(to_jsonable(item)))
    assert wire["level"] == "story" and wire["parent"] == {"id": "e1", "level": "epic", "key": "AA-1"}
    assert WorkItem.from_dict(wire) == item


def test_from_dict_rejects_unknown_fields():
    with pytest.raises(ValueError, match="unknown WorkItem fields: priority"):
        WorkItem.from_dict({"level": "story", "title": "t", "priority": "high"})


def test_iteration_export():
    it = Iteration("202609", id="c1", start=date(2026, 9, 1), end=date(2026, 9, 30), state=IterationState.ACTIVE)
    assert to_jsonable(it) == {
        "name": "202609", "id": "c1", "start": "2026-09-01", "end": "2026-09-30", "state": "active",
    }


# --- capabilities ----------------------------------------------------------

PLANE_LEVELS = {
    Level.INITIATIVE: Materialization.NONE,
    Level.EPIC: Materialization.TYPE,
    Level.FEATURE: Materialization.CONTAINER,
    Level.STORY: Materialization.TYPE,
    Level.BUG: Materialization.TYPE,
    Level.TASK: Materialization.TYPE,
}
INITIATIVE_AS_LABEL = {Level.INITIATIVE: CollapseRule(CollapseTarget.LABEL, "initiative:{name}")}


def test_capabilities_accepts_a_plane_shaped_record():
    caps = Capabilities(
        "plane", PLANE_LEVELS, DescriptionFormat.HTML,
        states_via_transitions=False, native_idempotency_key=True, collapse=INITIATIVE_AS_LABEL,
    )
    assert caps.materializes(Level.FEATURE) and not caps.materializes(Level.INITIATIVE)
    assert to_jsonable(caps)["levels"]["feature"] == "container"
    assert to_jsonable(caps)["collapse"]["initiative"]["target"] == "label"


def test_capabilities_requires_every_level():
    with pytest.raises(ValueError, match="miss levels: bug, task"):
        Capabilities(
            "x", {lv: PLANE_LEVELS[lv] for lv in PLANE_LEVELS if lv not in (Level.BUG, Level.TASK)},
            DescriptionFormat.MARKDOWN, states_via_transitions=False, native_idempotency_key=False,
            collapse=INITIATIVE_AS_LABEL,
        )


def test_an_absent_level_needs_no_collapse_rule_and_is_not_materialized():
    caps = Capabilities(
        "plane", {**PLANE_LEVELS, Level.BUG: Materialization.ABSENT}, DescriptionFormat.HTML,
        states_via_transitions=False, native_idempotency_key=True, collapse=INITIATIVE_AS_LABEL,
    )
    assert not caps.materializes(Level.BUG) and caps.materializes(Level.STORY)
    assert to_jsonable(caps)["levels"]["bug"] == "absent"


def test_capabilities_collapse_rules_match_unmaterialized_levels():
    with pytest.raises(ValueError, match="without a collapse rule: initiative"):
        Capabilities("x", PLANE_LEVELS, DescriptionFormat.HTML, states_via_transitions=False, native_idempotency_key=True)
    with pytest.raises(ValueError, match="collapse rules for materialized levels: epic"):
        Capabilities(
            "x", PLANE_LEVELS, DescriptionFormat.HTML, states_via_transitions=False, native_idempotency_key=True,
            collapse={**INITIATIVE_AS_LABEL, Level.EPIC: CollapseRule(CollapseTarget.LABEL)},
        )
