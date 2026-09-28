"""The MCP server's domain service against the fake Plane transport —
propose → commit (D12), title-case warnings (D14), error wording."""

from datetime import datetime, timezone

import pytest

from adapters.base import AuthError, Blocked, RateLimited, TransportError
from schema.intake import Intake, render
from server.service import DRAFT_TTL, BoardService, ToolFailure
from tests import fake_plane as fp
from tests.test_intake import SPLIT
from tests.test_plane_adapter import CONFIG, make


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def service(config=None):
    adapter, transport = make(config=config)
    clock = Clock()
    return BoardService(adapter, clock=clock), transport, clock


def item_posts(t):
    return [b for m, p, _, b in t.calls if m == "POST" and p == f"{fp.PP}/work-items/"]


STORY = dict(
    intake_id="req-0007", level="story", title="Requester Can Attach A Screenshot",
    description="As a requester I can attach a screenshot.", part="story-2",
    parent="AA-1", feature="Intake", iteration="202609", labels=["feature"],
)


def propose(svc, **overrides):
    args = {**STORY, **overrides}
    return svc.propose_item(args.pop("intake_id"), args.pop("level"), args.pop("title"), **args)


# --- propose ---------------------------------------------------------------------


def test_propose_writes_nothing_and_adds_the_conventions():
    svc, t, _ = service()
    out = propose(svc)
    assert {m for m, *_ in t.calls} == {"GET"}
    p = out["preview"]
    assert p["labels"] == ["feature", "needs-review"]
    assert p["external_id"] == "req-0007/story-2"
    assert p["state"] == "backlog"
    assert p["parent"]["key"] == "AA-1" and p["parent"]["level"] == "epic"
    assert p["feature"] == {"id": fp.M_INTAKE, "name": "Intake"}
    assert p["iteration"] == {"id": fp.C_202609, "name": "202609"}
    assert out["warnings"] == [] and out["existing"] is None and out["confirm"] == "always"
    assert out["expires_at"] == "2026-09-22T12:30:00+00:00"


def test_propose_reports_every_board_problem_at_once_and_stores_nothing():
    svc, _, _ = service()
    with pytest.raises(ToolFailure) as err:
        propose(svc, feature="Nope", labels=["wontfix"], assignees=["nobody"], parent=None)
    msg = str(err.value)
    assert "no feature 'Nope'" in msg and "wontfix" in msg and "nobody" in msg
    assert svc._drafts == {}


def test_propose_checks_placement_against_the_model():
    svc, _, _ = service()
    with pytest.raises(ToolFailure, match="a task must have a parent"):
        propose(svc, level="task", parent=None, feature=None)
    with pytest.raises(ToolFailure, match="cannot be parented under a story"):
        propose(svc, parent="AA-2")


def test_propose_refuses_a_closed_iteration():
    svc, _, _ = service()
    with pytest.raises(ToolFailure, match="'202608' is closed"):
        propose(svc, iteration="202608")


def test_propose_refuses_while_the_config_does_not_fit_the_board():
    svc, t, _ = service(config={**CONFIG, "labels": {"review": "review-me"}})
    with pytest.raises(ToolFailure, match="nothing was written.*describe_board"):
        propose(svc)
    assert {m for m, *_ in t.calls} == {"GET"}


def test_title_case_warns_and_suggests_but_the_confirmed_title_lands():
    cfg = {**CONFIG, "naming": {"iteration": "YYYYMM", "item_case": "title"}}
    svc, t, _ = service(config=cfg)
    out = propose(svc, title="requester can attach a screenshot")
    assert out["suggested_title"] == "Requester Can Attach A Screenshot"
    assert "propose again with that title" in out["warnings"][0]
    svc.commit_item(out["token"])
    assert item_posts(t)[0]["name"] == "requester can attach a screenshot"


def test_propose_flags_an_external_id_that_already_exists():
    svc, t, _ = service()
    out = propose(svc, intake_id="req-0001", part="", feature=None, iteration=None)
    assert out["existing"]["key"] == "AA-2"
    assert "AA-2 already has external_id 'req-0001'" in out["warnings"][0]
    assert svc.commit_item(out["token"])["already_existed"] is True
    assert item_posts(t) == []


# --- from an intake record -------------------------------------------------------


def test_a_story_from_an_intake_lands_placed_with_its_criteria_and_the_review_label():
    svc, t, _ = service()
    epic = svc.propose_item(intake=SPLIT, part="epic")
    assert epic["preview"]["external_id"] == "20260923-export-csv/epic"
    with pytest.raises(ToolFailure, match="Part 'epic' of intake '20260923-export-csv' is not on the board yet"):
        svc.propose_item(intake=SPLIT, part="csv")
    epic_key = svc.commit_item(epic["token"])["item"]["key"]

    out = svc.propose_item(intake=SPLIT, part="csv")
    p = out["preview"]
    assert (p["level"], p["title"], p["external_id"]) == ("story", "Export Reports as CSV", "20260923-export-csv/csv")
    assert p["parent"]["key"] == epic_key and p["parent"]["level"] == "epic"
    assert p["feature"]["name"] == "Intake" and p["iteration"]["name"] == "202609"
    assert p["description"] == render(Intake.from_dict(SPLIT), "csv")
    assert p["labels"] == ["needs-review"]
    svc.commit_item(out["token"])
    story = item_posts(t)[-1]
    assert "<h2>Acceptance criteria</h2><ol><li><strong>Given</strong> a saved report" in story["description_html"]
    assert story["labels"] == [fp.L_REVIEW] and story["type_id"] == fp.T_STORY


@pytest.mark.parametrize(
    "kwargs, match",
    [
        (dict(part="csv", title="Other"), "the record supplies title; leave them out"),
        (dict(part="pdf"), "has no part 'pdf'"),
        (dict(part="epic", problem=""), "problem is empty"),
        (dict(part="epic", urgency="asap"), "'asap' is not a valid Urgency"),
        (dict(part="epic", parts=[]), "at least one part"),
    ],
)
def test_a_bad_intake_is_explained_before_the_board_is_read(kwargs, match):
    svc, t, _ = service()
    part, title = kwargs.pop("part"), kwargs.pop("title", "")
    with pytest.raises(ToolFailure, match=match):
        svc.propose_item(title=title, intake={**SPLIT, **kwargs}, part=part)
    assert t.calls == []


# --- commit ----------------------------------------------------------------------


def test_commit_writes_exactly_the_draft():
    svc, t, _ = service()
    done = svc.commit_item(propose(svc)["token"])
    [body] = item_posts(t)
    assert body["name"] == "Requester Can Attach A Screenshot"
    assert body["type_id"] == fp.T_STORY and body["parent"] == fp.I_EPIC and body["state"] == fp.S_BACKLOG
    assert body["labels"] == [fp.L_FEATURE, fp.L_REVIEW]
    assert (body["external_id"], body["external_source"]) == ("req-0007/story-2", "agentic_administration")
    new_id = done["item"]["id"]
    assert t.bodies("POST", "/module-issues/") == [{"issues": [new_id]}]
    assert t.bodies("POST", "/cycle-issues/") == [{"issues": [new_id]}]
    assert done["already_existed"] is False and done["item"]["key"].startswith("AA-")


def test_a_retried_commit_returns_the_item_instead_of_duplicating_it():
    svc, t, _ = service()
    token = propose(svc)["token"]
    first = svc.commit_item(token)
    again = svc.commit_item(token)
    assert len(item_posts(t)) == 1
    assert again["already_existed"] is True and again["item"]["id"] == first["item"]["id"]
    assert len(t.bodies("POST", "/cycle-issues/")) == 1  # nothing left to finish


def test_a_retry_finishes_what_a_failed_commit_left_off():
    svc, t, _ = service()
    token = propose(svc)["token"]
    wall = f"POST {fp.PP}/cycles/{fp.C_202609}/cycle-issues/"
    t.fail[wall] = Blocked("HTTP 403 answered by an edge wall (Cloudflare), not Plane")
    with pytest.raises(ToolFailure, match="will not duplicate"):
        svc.commit_item(token)
    del t.fail[wall]
    again = svc.commit_item(token)
    assert len(item_posts(t)) == 1
    assert again["already_existed"] is True and again["item"]["iteration"] == fp.C_202609


def test_an_expired_or_unknown_token_writes_nothing():
    svc, t, clock = service()
    token = propose(svc)["token"]
    clock.now += DRAFT_TTL
    with pytest.raises(ToolFailure, match="expired.*propose_item again"):
        svc.commit_item(token)
    with pytest.raises(ToolFailure, match="Unknown draft token"):
        svc.commit_item(token)
    assert item_posts(t) == []


# --- reads, other writes, errors ------------------------------------------------------


def test_describe_board_reports_the_confirm_mode_and_naming():
    svc, _, _ = service(config={**CONFIG, "confirm": "never"})
    out = svc.describe_board()
    assert out["confirm"] == "never" and out["review_label"] == "needs-review"
    assert out["problems"] == [] and out["capabilities"]["levels"]["feature"] == "container"
    assert out["naming"] == {"iteration": "YYYYMM", "item_case": "any"}


def test_other_writes_pass_through_and_nothing_deletes():
    svc, t, _ = service()
    assert svc.find_items(external_id="req-0001")[0]["key"] == "AA-2"
    assert [i["key"] for i in svc.find_items(iteration="202609")] == ["AA-2"]
    updated = svc.update_item("AA-2", state="in_progress", labels=["feature"])
    assert updated["state"] == "in_progress" and updated["labels"] == ["feature"]
    assert svc.add_comment("AA-2", "Looks good")["body"] == "Looks good"
    made = svc.create_iteration("202610", "2026-10-01", "2026-10-31")
    assert (made["name"], made["start"], made["end"]) == ("202610", "2026-10-01", "2026-10-31")
    assert svc.move_to_iteration(["AA-1"], "202609") == {"moved": ["AA-1"], "iteration": "202609"}
    assert svc.close_iteration("202609")["state"] == "closed"
    assert "DELETE" not in {m for m, *_ in t.calls}
    assert not [n for n in dir(BoardService) if "delete" in n or "remove" in n]


@pytest.mark.parametrize(
    "call, match",
    [
        (lambda s: s.find_items(level="saga"), "level must be one of: initiative, epic"),
        (lambda s: s.update_item("AA-2", state="blocked"), "state must be one of"),
        (lambda s: s.create_iteration("202610", "next monday"), "ISO date"),
        (lambda s: s.add_comment("AA-2", "  "), "empty"),
        (lambda s: s.get_item("AA-99"), "Not found.*Check the key"),
    ],
)
def test_bad_input_is_explained(call, match):
    svc, _, _ = service()
    with pytest.raises(ToolFailure, match=match):
        call(svc)


@pytest.mark.parametrize(
    "exc, hint",
    [
        (RateLimited("rate limited on GET"), "Wait about a minute, then retry"),
        (Blocked("edge wall"), "Wait several minutes"),
        (AuthError("HTTP 401"), "retrying will not help"),
        (TransportError("timed out"), "Retry shortly"),
    ],
)
def test_adapter_errors_become_actionable_failures(exc, hint):
    svc, t, _ = service()
    t.fail[f"GET {fp.WS}/work-items/AA-1/"] = exc
    with pytest.raises(ToolFailure, match=hint):
        svc.get_item("AA-1")
