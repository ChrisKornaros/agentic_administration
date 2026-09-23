"""The intake record: validation, the JSON round trip, and the Markdown
rendering (checked through the Plane renderer, the subset every adapter
must handle)."""

import pytest

from adapters.plane.markdown import render as to_html
from schema.intake import Intake, InvalidIntake, Urgency, render
from server.model import Level, to_jsonable

SPLIT = {
    "id": "20260923-export-csv",
    "problem": "Finance re-types report totals by hand each month.",
    "outcome": "A report downloads as a file a spreadsheet opens.",
    "constraints": ["no new paid service"],
    "urgency": "medium",
    "related": ["AA-2"],
    "parts": [
        {"part": "epic", "level": "epic", "title": "Report Exports"},
        {
            "part": "csv", "level": "story", "title": "Export Reports as CSV",
            "acceptance": [{"given": "a saved report.", "when": "I choose\nExport > CSV", "then": "a .csv downloads"}],
            "placement": {"parent": "#epic", "feature": "Intake", "iteration": "202609"},
        },
    ],
}


def record(**overrides) -> Intake:
    return Intake.from_dict({**SPLIT, **overrides})


def test_a_split_is_valid_and_round_trips_as_json():
    rec = record()
    assert rec.validate() == []
    assert rec.urgency is Urgency.MEDIUM and rec.get_part("csv").level is Level.STORY
    assert Intake.from_dict(to_jsonable(rec)) == rec


def test_one_item_is_one_unnamed_part():
    rec = record(parts=[{"level": "bug", "title": "Export Drops The Last Row",
                         "acceptance": [{"given": "g", "when": "w", "then": "t"}]}])
    assert rec.check() is rec and rec.get_part().part == ""


def test_every_problem_is_reported_at_once():
    rec = record(
        id="has/slash", problem=" ", constraints=[""],
        parts=[
            {"part": "epic", "level": "epic", "title": "Report Exports", "placement": {"feature": "Intake"}},
            {"part": "csv", "level": "story", "title": "Export Reports as CSV", "placement": {"parent": "#nope"}},
            {"part": "csv", "level": "task", "title": ""},
            {"level": "story", "title": "Pdf", "acceptance": [{"given": "g", "when": "", "then": " "}],
             "placement": {"parent": "#csv"}},
        ],
    )
    with pytest.raises(InvalidIntake) as err:
        rec.check()
    problems = err.value.problems
    for expected in [
        "id 'has/slash' must be",
        "problem is empty",
        "a constraint is empty",
        "part names repeat: 'csv'",
        "part 'epic': a epic cannot carry a feature",
        "part 'csv': a story needs at least one acceptance criterion",
        "part 'csv': parent '#nope' names no other part of this intake",
        "part 'csv': title is empty",
        "part 'csv': a task must have a parent",
        "part '': needs a name: the intake has several parts",
        "part '': acceptance 1 has an empty when / then",
    ]:
        assert any(p.startswith(expected) for p in problems), (expected, problems)


def test_a_sibling_parent_is_checked_against_the_model():
    rec = record(parts=[
        SPLIT["parts"][1],
        {"part": "pdf", "level": "story", "title": "Export Reports as PDF",
         "acceptance": [{"given": "g", "when": "w", "then": "t"}], "placement": {"parent": "#csv"}},
    ])
    assert "part 'pdf': a story cannot be parented under a story (allowed: epic)" in rec.validate()


def test_unknown_fields_and_parts_are_refused():
    with pytest.raises(ValueError, match="unknown Intake fields: priority"):
        record(priority="high")
    with pytest.raises(ValueError, match="unknown Criterion fields: and"):
        record(parts=[{"level": "story", "title": "T",
                       "acceptance": [{"given": "g", "when": "w", "then": "t", "and": "x"}]}])
    with pytest.raises(KeyError, match="no part 'pdf'.*'epic', 'csv'"):
        record().get_part("pdf")


def test_render_is_the_shared_context_plus_the_parts_criteria():
    assert render(record(), "csv") == (
        "## Problem\n\nFinance re-types report totals by hand each month.\n\n"
        "## Outcome\n\nA report downloads as a file a spreadsheet opens.\n\n"
        "## Acceptance criteria\n\n"
        "1. **Given** a saved report, **when** I choose Export > CSV, **then** a .csv downloads\n\n"
        "## Constraints\n\n- no new paid service\n\n"
        "## Related\n\n- AA-2\n\n"
        "Intake `20260923-export-csv`, part `csv` · urgency (the requester's): medium\n"
    )


def test_render_leaves_out_empty_sections():
    rec = record(constraints=[], related=[], urgency=None)
    assert render(rec, "epic") == (
        "## Problem\n\nFinance re-types report totals by hand each month.\n\n"
        "## Outcome\n\nA report downloads as a file a spreadsheet opens.\n\n"
        "Intake `20260923-export-csv`, part `epic`\n"
    )


def test_the_rendering_survives_the_plane_renderer():
    html = to_html(render(record(), "csv"))
    assert "<h2>Acceptance criteria</h2><ol><li><strong>Given</strong> a saved report, " in html
    assert "<strong>when</strong> I choose Export &gt; CSV, <strong>then</strong> a .csv downloads</li></ol>" in html
    assert "<h2>Constraints</h2><ul><li>no new paid service</li></ul>" in html
    assert "<code>20260923-export-csv</code>" in html
    assert "##" not in html and "**" not in html  # nothing left as literal Markdown
