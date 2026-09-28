"""Offline tests for the conformance runner and cases, against the fake
Plane transport — a fresh project, as Plane creates one."""

from collections import Counter
from datetime import date

import pytest

from adapters.base import Blocked, NotFound
from adapters.jira import JiraAdapter
from adapters.plane import PlaneAdapter
from conformance import __main__ as cli
from conformance import runner
from conformance.cases import Context, Skipped
from server.config import BoardConfig
from tests import fake_jira as fj
from tests import fake_plane as fp
from tests import test_jira_adapter as tests_jira

CONFIG = {
    "backend": "plane",
    "connection": {"token_env": "PLANE_API_KEY", "workspace": "ws", "project": "agentic_administration"},
    "levels": {
        "initiative": {"collapse": "description_line", "template": "**Initiative:** {name}"},
        "epic": {"type": "Epic"},
        "feature": {"container": "module"},
        "story": {"type": "Story"},
        "bug": {"type": "Bug"},
        "task": {"type": "Task"},
    },
    "states": {"backlog": "Backlog", "todo": "Todo", "in_progress": "In Progress", "done": "Done", "cancelled": "Cancelled"},
    "labels": {"review": "needs-review", "taxonomy": ["bug", "feature", "chore", "docs"]},
    "naming": {"iteration": "YYYYMM", "item_case": "title"},
}
TODAY = date(2026, 9, 22)
ALL = ["provision", "describe", "epic", "placement", "hierarchy", "update", "iterations", "close", "rollover", "no-delete"]


def process(transport):
    """One `python -m conformance` process against the fake board."""
    cfg = BoardConfig.from_dict(CONFIG).check()
    adapter = PlaneAdapter(cfg, transport, secret=lambda name: "unused", today=lambda: TODAY)
    return Context(adapter, cfg, "20260922", TODAY, lambda: transport.log)


def go(ctx, state, lines=None):
    echo = lines.append if lines is not None else (lambda line: None)
    return runner.run(runner.cases_for("plane"), ctx, state, save=lambda s: None, echo=echo)


def new_state():
    return {"run_id": "20260922", "cases": {}, "ids": {}, "wire": {}}


def statuses(state):
    return {name: c["status"] for name, c in state["cases"].items()}


def notes(state, case):
    return "\n".join(state["cases"][case]["notes"])


def test_a_fresh_board_is_provisioned_and_passes_every_case():
    t = fp.FakeTransport(fp.fresh_routes())
    state = new_state()
    assert go(process(t), state) == runner.PASS
    assert statuses(state) == {name: "pass" for name in ALL}

    assert "PATCH …/features turned on work_item_types, epics" in notes(state, "provision")
    assert "work-item types created: Bug, Story, Task" in notes(state, "provision")
    assert "labels created via POST …/labels/: bug, chore, docs, feature, needs-review" in notes(state, "provision")
    assert "find_items(external_id=…) finds exactly it in 1 call" in notes(state, "epic")
    assert "the tracker accepted" in notes(state, "hierarchy")
    assert "while its end date was today — the end day is still open" in notes(state, "iterations")
    assert "dates read back as written: 202609 2026-09-01–2026-09-22, 202610 2026-10-01–2026-10-31" in notes(state, "iterations")
    assert "a closed iteration refuses new items" in notes(state, "close")
    # the unfinished story leaves the closed cycle; the done task stays
    assert "create_iteration('202610') found the existing iteration: no duplicate" in notes(state, "rollover")
    assert "moved out of closed 202609: AA-101 now read 202610" in notes(state, "rollover")
    assert "1 done or cancelled item(s) stayed in 202609" in notes(state, "rollover")
    assert [c["name"] for c in t.routes[f"GET {fp.PP}/cycles/"]].count("202610") == 1

    # nothing deleted, and the record's wire totals are the transport's own
    assert state["wire"] == dict(Counter(m for m, _ in t.log))
    assert "DELETE" not in state["wire"]
    assert set(state["ids"]) == {"epic", "feature", "story", "bug", "task", "iteration_current", "iteration_next"}
    # the review label went on at create and came off at update
    story = next(r for r in t._items() if r["id"] == state["ids"]["story"])
    assert story["labels"] == [] and story["min_module_name"] == "Conformance 20260922"


def test_ui_only_features_stop_for_the_operator_then_the_run_resumes():
    t = fp.FakeTransport(fp.fresh_routes())
    t.features_patchable = False
    state = new_state()
    assert go(process(t), state) == runner.STOP
    assert statuses(state) == {"provision": "stop"}
    assert "turn on work_item_types, epics in Plane → agentic_administration → Project Settings → Features" in notes(state, "provision")
    assert [m for m, _ in t.log if m != "GET"] == ["PATCH"]  # nothing created before the gate

    # the operator flips them in the UI; a new process picks up from provision
    t.routes[f"GET {fp.PP}/features/"].update(work_item_types=True, epics=True)
    t.routes[f"GET {fp.PP}/work-item-types/"].append({"id": fp.T_EPIC, "name": "Epic", "level": 1, "is_epic": True})
    t2 = fp.FakeTransport(t.routes)
    assert go(process(t2), state) == runner.PASS
    assert "features already on" in notes(state, "provision")
    assert state["wire"]["PATCH"] == 1 + sum(1 for m, _ in t2.log if m == "PATCH")


def test_the_edge_wall_mid_run_resumes_without_redoing_writes():
    t = fp.FakeTransport(fp.fresh_routes())
    t.fail[f"POST {fp.PP}/cycles/"] = Blocked("HTTP 403 on POST cycles answered by an edge wall (Cloudflare), not Plane")
    state = new_state()
    lines: list[str] = []
    assert go(process(t), state, lines) == runner.STOP
    assert statuses(state) == {**{n: "pass" for n in ALL[:6]}, "iterations": "stop"}
    assert any("re-run to resume" in line for line in lines)

    t2 = fp.FakeTransport(t.routes)
    lines = []
    assert go(process(t2), state, lines) == runner.PASS
    assert lines[0].strip().startswith("PASS  provision") and "recorded" in lines[0]
    # the resumed process wrote no items or labels again
    assert not [p for m, p in t2.log if m == "POST" and p.endswith(("/work-items/", "/labels/", "/modules/"))]
    posts = sum(1 for m, _ in t.log + t2.log if m == "POST")
    assert state["wire"]["POST"] == posts


def test_a_broken_contract_fails_and_stops_the_run():
    t = fp.FakeTransport(fp.fresh_routes())
    t.fail[f"GET {fp.PP}/work-items/"] = NotFound("HTTP 404")  # a lookup that never finds
    state = new_state()
    assert go(process(t), state) == runner.FAIL
    assert statuses(state) == {"provision": "pass", "describe": "pass", "epic": "fail"}
    assert "failed: find_items(external_id='conformance:20260922:epic') returned [], expected exactly AA-100" in notes(state, "epic")


def test_a_case_added_to_a_finished_run_runs_on_resume_and_no_delete_runs_again():
    t = fp.FakeTransport(fp.fresh_routes())
    state = new_state()
    assert go(process(t), state) == runner.PASS
    del state["cases"]["rollover"]  # as a record written before the case existed
    state["cases"]["no-delete"]["at"] = "then"
    lines: list[str] = []
    assert go(process(t), state, lines) == runner.PASS
    ran = [line.split()[1] for line in lines if line.startswith("  ") and "recorded" not in line and not line.strip().startswith("-")]
    assert ran == ["rollover", "no-delete"]
    assert "holds nothing unfinished" in notes(state, "rollover")  # the first process already rolled the story
    assert state["cases"]["no-delete"]["at"] != "then"


def test_an_iteration_closed_by_an_earlier_run_is_a_recorded_skip():
    routes = fp.fresh_routes()
    routes[f"GET {fp.PP}/cycles/"].append(
        {"id": fp.C_202609, "name": "202609", "start_date": "2026-09-01", "end_date": "2026-09-10", "status": "completed"})
    state = new_state()
    assert go(process(fp.FakeTransport(routes)), state) == runner.PASS
    assert state["cases"]["iterations"]["status"] == "skip"
    assert "202609 is already closed" in notes(state, "iterations")
    assert state["cases"]["close"]["status"] == "pass"


def test_dry_run_lists_the_cases_without_a_call(tmp_path, monkeypatch, capsys):
    board = tmp_path / "throwaway.toml"
    board.write_text(
        'backend = "plane"\n[connection]\ntoken_env = "PLANE_API_KEY"\nworkspace = "ws"\nproject = "p"\n'
        '[levels]\nepic = { type = "Epic" }\nstory = { type = "Story" }\nbug = { type = "Bug" }\n'
        'task = { type = "Task" }\nfeature = { container = "module" }\n'
        'initiative = { collapse = "description_line", template = "**Initiative:** {name}" }\n'
        '[states]\nbacklog = "Backlog"\ntodo = "Todo"\nin_progress = "In Progress"\ndone = "Done"\ncancelled = "Cancelled"\n'
        '[labels]\nreview = "needs-review"\n'
    )

    def no_harness(*args, **kwargs):
        raise AssertionError("a dry run built an adapter")

    monkeypatch.setitem(cli.HARNESSES, "plane", no_harness)
    assert cli.main([str(board), "--dry-run", "--run-id", "t1", "--reports", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"record: {tmp_path / 'throwaway-t1.json'}" in out
    for name in ALL:
        assert f"  {name}" in out
    assert out.count("[not run]") == len(ALL)
    assert not (tmp_path / "throwaway-t1.json").exists()


def test_bad_config_exits_2(tmp_path, capsys):
    board = tmp_path / "bad.toml"
    board.write_text('backend = "plane"\n')
    assert cli.main([str(board), "--dry-run", "--reports", str(tmp_path)]) == 2
    assert "invalid board config" in capsys.readouterr().err


def test_a_backend_without_a_provisioner_skips_provisioning():
    with pytest.raises(Skipped, match="no provisioner for generic; provision the board by hand"):
        runner.cases_for("generic")[0].run(process(fp.FakeTransport()))


# --- Jira, against the fake Jira transport --------------------------------------

JIRA = tests_jira.CONFIG


def jira_process(fake, today=date(2026, 9, 27)):
    cfg = BoardConfig.from_dict(JIRA).check()
    adapter = JiraAdapter(cfg, fake, secret=lambda name: "unused", today=lambda: today)
    return Context(adapter, cfg, "20260927", today, lambda: fake.log)


def test_jira_passes_every_case_with_feature_collapsed_to_a_label():
    fake = fj.FakeJira()
    state = new_state()
    assert runner.run(runner.cases_for("jira"), jira_process(fake), state, save=lambda s: None, echo=lambda l: None) == runner.PASS
    assert statuses(state) == {name: "pass" for name in ALL}
    assert "nothing to create" in notes(state, "provision")
    assert "the feature collapsed: the story carries it as ['feature:Conformance-20260927']" in notes(state, "placement")
    assert "the tracker accepted" in notes(state, "hierarchy")  # as live Jira did (AGADM-5)
    assert "dates read back as written: 202609 2026-09-01–2026-09-27, 202610 2026-10-01–2026-10-31" in notes(state, "iterations")
    assert "a closed iteration refuses new items" in notes(state, "close")
    # the story rolls, and its done sub-task comes along, as on live Jira (AGADM-4)
    assert "moved out of closed 202609: AA-2 now read 202610" in notes(state, "rollover")
    assert "0 done or cancelled item(s) stayed in 202609; AA-4 left with a moved parent" in notes(state, "rollover")
    assert "DELETE" not in state["wire"]
    story = fake.issues[state["ids"]["story"]]["fields"]
    assert [s["name"] for s in story[fj.SPRINT_FIELD]] == ["202609", "202610"]  # the closed sprint stays in its history
    assert story["labels"] == ["xid:conformance:20260927:story"]  # review cleared, the key kept


def test_jira_provision_stops_for_the_operator_when_the_project_does_not_fit():
    fake = fj.FakeJira()
    fake.statuses = [s for s in fake.statuses if s["name"] != "Cancelled"]
    state = new_state()
    assert runner.run(runner.cases_for("jira"), jira_process(fake), state, save=lambda s: None) == runner.STOP
    assert "states.cancelled: no status named 'Cancelled'" in notes(state, "provision")
    assert {m for m, _ in fake.log} == {"GET"}


def test_a_bad_token_on_the_features_patch_is_a_failure_not_a_ui_instruction():
    from adapters.base import AuthError

    t = fp.FakeTransport(fp.fresh_routes())
    t.fail[f"PATCH {fp.PP}/features/"] = AuthError("HTTP 401 on PATCH features/: not authorized")
    state = new_state()
    assert go(process(t), state) == runner.FAIL
    assert "AuthError: HTTP 401" in notes(state, "provision")
    assert "Project Settings" not in notes(state, "provision")
