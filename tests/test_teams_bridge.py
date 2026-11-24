"""The chat bridge in examples/teams/: who it serves on which billing, one
session a conversation, a yes before each write, and its Agent SDK side tied
to the Agent SDK chat's constants. The bridge is standard library only, so
it runs here against a fake agent; `agent.py` needs the optional SDK and is
read without importing it."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.test_docs import DOC_TOOLS
from tests.test_examples import sdk_constant
from tests.test_issues import ISSUE_TOOLS
from tests.test_mcp_app import TOOLS

ROOT = Path(__file__).resolve().parents[1]
TEAMS = ROOT / "examples" / "teams"
AGENT = TEAMS / "agent.py"

_spec = importlib.util.spec_from_file_location("teams_bridge", TEAMS / "bridge.py")
bridge = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bridge  # a dataclass looks its module up by name
_spec.loader.exec_module(bridge)

OWNER, COWORKER, STRANGER = "owner-id", "coworker-id", "stranger-id"


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeAgent:
    """Records each turn; a turn whose text starts `write` asks for a write first,
    and one whose text is `boom` dies."""

    def __init__(self) -> None:
        self.turns: list[tuple[str, bool, str]] = []
        self.allowed: list[bool] = []
        self.gate: asyncio.Event | None = None  # set, a turn waits here before answering

    async def run(self, session_id, resume, text, confirm):
        self.turns.append((session_id, resume, text))
        if text == "boom":
            raise RuntimeError("the agent fell over")
        if self.gate:
            await self.gate.wait()
        if text.startswith("write"):
            ok = await confirm("commit_item", {"token": "t-1"})
            self.allowed.append(ok)
            yield "Created AA-1." if ok else "Nothing was written."
            return
        yield "   "  # blank text is not posted
        yield f"echo: {text}"


class Chat:
    """A conversation's answers, in order."""

    def __init__(self) -> None:
        self.said: list[str] = []

    async def __call__(self, text: str) -> None:
        self.said.append(text)


def make(tmp_path, *, mode="metered", allowed=(COWORKER,), timeout=5.0, agent=None):
    agent = agent or FakeAgent()
    b = bridge.Bridge(agent, bridge.Sessions(tmp_path / "state" / "sessions.json"), owner=OWNER, allowed=allowed,
                      mode=mode, confirm_timeout=timeout)
    return b, agent


async def settle(b, conversation="c1") -> None:
    """Let a started turn run until it ends or waits for a yes."""
    for _ in range(200):
        await asyncio.sleep(0.005)
        if b.waiting(conversation) or not b.busy(conversation):
            return
    raise AssertionError("the turn neither ended nor asked")


# -- whose usage pays ----------------------------------------------------------------------


@pytest.mark.parametrize("environ, mode", [
    ({}, "plan"),
    ({"ANTHROPIC_API_KEY": ""}, "plan"),
    ({"CLAUDE_CODE_USE_FOUNDRY": "0"}, "plan"),
    ({"CLAUDE_CODE_OAUTH_TOKEN": "a plan login's token"}, "plan"),
    ({"ANTHROPIC_API_KEY": "a-key"}, "metered"),
    ({"ANTHROPIC_AUTH_TOKEN": "a-token"}, "metered"),
    ({"CLAUDE_CODE_USE_FOUNDRY": "1"}, "metered"),
    ({"CLAUDE_CODE_USE_BEDROCK": "true"}, "metered"),
    ({"CLAUDE_CODE_USE_VERTEX": "1"}, "metered"),
])
def test_billing_is_metered_only_with_a_pay_by_use_credential(environ, mode):
    assert bridge.billing(environ) == mode


@pytest.mark.anyio
async def test_on_a_plan_login_only_the_owner_is_served_whatever_the_allow_list_says(tmp_path):
    b, agent = make(tmp_path, mode="plan")
    chat = Chat()
    await b.handle(COWORKER, "c1", "hello", chat)
    assert chat.said == [bridge.REFUSED_ON_A_PLAN] and agent.turns == []
    await b.handle(OWNER, "c1", "hello", chat)
    assert chat.said[-1] == "echo: hello" and len(agent.turns) == 1


@pytest.mark.anyio
async def test_on_metered_billing_the_allow_list_is_served_and_nobody_else(tmp_path):
    b, agent = make(tmp_path)
    chat = Chat()
    await b.handle(COWORKER, "c1", "hello", chat)
    await b.handle(STRANGER, "c1", "hello", chat)
    assert chat.said == ["echo: hello", bridge.REFUSED] and len(agent.turns) == 1


# -- one conversation, one session ---------------------------------------------------------


@pytest.mark.anyio
async def test_the_first_message_starts_a_session_and_later_ones_resume_it_across_restarts(tmp_path):
    b, agent = make(tmp_path)
    await b.handle(OWNER, "c1", "one", Chat())
    await b.handle(OWNER, "c1", "two", Chat())
    await b.handle(OWNER, "c2", "other", Chat())
    (first, r1, _), (second, r2, _), (other, r3, _) = agent.turns
    assert (r1, r2, r3) == (False, True, False) and first == second != other
    restarted, agent2 = make(tmp_path)
    await restarted.handle(OWNER, "c1", "three", Chat())
    assert agent2.turns == [(first, True, "three")]
    assert json.loads((tmp_path / "state" / "sessions.json").read_text()) == {"c1": first, "c2": other}


@pytest.mark.anyio
async def test_a_first_turn_that_dies_leaves_no_session_to_resume(tmp_path):
    b, agent = make(tmp_path)
    chat = Chat()
    await b.handle(OWNER, "c1", "boom", chat)
    await b.handle(OWNER, "c1", "again", chat)
    assert chat.said == [bridge.FAILED, "echo: again"]
    assert [resume for _, resume, _ in agent.turns] == [False, False] and agent.turns[0][0] != agent.turns[1][0]


@pytest.mark.anyio
async def test_a_later_turn_that_dies_keeps_the_session(tmp_path):
    b, agent = make(tmp_path)
    for text in ("one", "boom", "two"):
        await b.handle(OWNER, "c1", text, Chat())
    assert [resume for _, resume, _ in agent.turns] == [False, True, True] and len({s for s, _, _ in agent.turns}) == 1


@pytest.mark.anyio
async def test_new_starts_the_conversation_over(tmp_path):
    b, agent = make(tmp_path)
    chat = Chat()
    await b.handle(OWNER, "c1", "one", chat)
    await b.handle(OWNER, "c1", " /NEW ", chat)
    await b.handle(OWNER, "c1", "two", chat)
    assert chat.said[1] == bridge.STARTED_OVER and len(agent.turns) == 2
    assert agent.turns[1][1] is False and agent.turns[0][0] != agent.turns[1][0]


@pytest.mark.anyio
async def test_a_redelivered_message_and_an_empty_one_start_no_turn(tmp_path):
    b, agent = make(tmp_path)
    chat = Chat()
    await b.handle(OWNER, "c1", "one", chat, message_id="m-1")
    await b.handle(OWNER, "c1", "one", chat, message_id="m-1")
    await b.handle(OWNER, "c1", "   ", chat, message_id="m-2")
    assert chat.said == ["echo: one"] and len(agent.turns) == 1


@pytest.mark.anyio
async def test_turns_in_one_conversation_run_in_order_and_other_conversations_do_not_wait(tmp_path):
    b, agent = make(tmp_path)
    agent.gate = asyncio.Event()
    first = asyncio.create_task(b.handle(OWNER, "c1", "one", Chat()))
    second = asyncio.create_task(b.handle(OWNER, "c1", "two", Chat()))
    elsewhere = asyncio.create_task(b.handle(OWNER, "c2", "other", Chat()))
    await asyncio.sleep(0.02)
    assert [text for _, _, text in agent.turns] == ["one", "other"] and b.busy("c1") and b.busy("c2")
    agent.gate.set()
    await asyncio.gather(first, second, elsewhere)
    assert [text for _, _, text in agent.turns] == ["one", "other", "two"] and not b.busy("c1")


@pytest.mark.anyio
async def test_started_is_called_for_a_turn_and_for_nothing_else(tmp_path):
    b, agent = make(tmp_path)
    calls: list[str] = []

    async def started() -> None:
        calls.append("started")

    chat = Chat()
    await b.handle(STRANGER, "c1", "hello", chat, started=started)
    await b.handle(OWNER, "c1", "/new", chat, started=started)
    await b.handle(OWNER, "c1", "one", chat, message_id="m-1", started=started)
    await b.handle(OWNER, "c1", "one", chat, message_id="m-1", started=started)
    turn = asyncio.create_task(b.handle(OWNER, "c1", "write it", chat, started=started))
    await settle(b)
    await b.handle(OWNER, "c1", "yes", chat, started=started)  # an answer is not a turn
    await turn
    assert calls == ["started", "started"] and len(agent.turns) == 2


# -- a yes before each write ---------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("answer, allowed, said", [
    ("yes", True, "Created AA-1."), (" Y ", True, "Created AA-1."),
    ("no", False, "Nothing was written."), ("sure, go on", False, "Nothing was written.")])
async def test_a_write_waits_for_the_senders_answer_and_only_yes_allows_it(tmp_path, answer, allowed, said):
    b, agent = make(tmp_path)
    chat = Chat()
    turn = asyncio.create_task(b.handle(OWNER, "c1", "write it", chat))
    await settle(b)
    assert b.waiting("c1") and "create the item I just previewed" in chat.said[0] and "t-1" not in chat.said[0]
    await b.handle(OWNER, "c1", answer, chat)
    await turn
    assert agent.allowed == [allowed] and chat.said[-1] == said
    assert len(agent.turns) == 1 and not b.waiting("c1")  # the answer was not a new turn


@pytest.mark.anyio
async def test_someone_else_in_the_conversation_cannot_answer_for_the_sender(tmp_path):
    b, agent = make(tmp_path)
    chat = Chat()
    turn = asyncio.create_task(b.handle(OWNER, "c1", "write it", chat))
    await settle(b)
    await b.handle(COWORKER, "c1", "yes", chat)
    assert chat.said[-1] == bridge.NOT_YOURS and b.waiting("c1") and agent.allowed == []
    await b.handle(OWNER, "c1", "yes", chat)
    await turn
    assert agent.allowed == [True]


@pytest.mark.anyio
async def test_no_answer_in_time_is_a_no(tmp_path):
    b, agent = make(tmp_path, timeout=0.02)
    chat = Chat()
    await b.handle(OWNER, "c1", "write it", chat)
    assert agent.allowed == [False] and chat.said[1:] == [bridge.NO_ANSWER, "Nothing was written."] and not b.waiting("c1")


def test_a_long_write_is_shown_cut():
    shown = bridge.write_request("update_item", {"description": "x" * 5000})
    assert len(shown) < bridge.ARGS_SHOWN + 300 and "(cut)" in shown


def test_a_write_is_asked_for_in_words_not_json():
    ask = "Reply **yes** to let it through. Anything else stops it."
    assert bridge.write_request("add_comment", {"ref": "AA-8", "body": "Reached it.\nSecond line.", "board": "sandbox"}) == (
        "I'm about to add a comment to **AA-8** on the **sandbox** board:\n\n"
        "**Comment:**\n\n> Reached it.\n> Second line.\n\n" + ask)
    assert bridge.write_request("update_item", {"ref": "AA-8", "state": "done", "labels": [], "title": None,
                                                "fields": {"Points": 3, "Blocked": False}}) == (
        "I'm about to update **AA-8**:\n\n- **State:** done\n- **Labels (replacing the current ones):** none\n"
        "- **Fields:** Points: 3, Blocked: no\n\n" + ask)
    assert bridge.write_request("move_to_iteration", {"items": ["AA-1", "AA-2"], "iteration": "Sprint 2"}) == (
        "I'm about to move AA-1, AA-2 into the iteration **Sprint 2**.\n\n" + ask)
    assert bridge.write_request("commit_item", {"token": "t-1", "board": "sandbox"}) == (
        "I'm about to create the item I just previewed on the **sandbox** board.\n\n" + ask)
    for shown in (bridge.write_request("add_comment", {"ref": "AA-8", "body": "x"}), bridge.write_request("commit_item", {})):
        assert "{" not in shown and "```" not in shown


def test_a_write_the_bridge_has_no_words_for_is_still_shown_in_full():
    assert bridge.write_request("some_new_write", {"target_date": "2026-01-02"}).startswith(
        "I'm about to run **some_new_write**:\n\n- **Target date:** 2026-01-02\n\n")
    assert "run **update_item**" in bridge.write_request("update_item", {"state": "done"})  # no ref: its words need one


# -- the Agent SDK side, read without importing it -----------------------------------------


def constant(name: str):
    for node in ast.parse(AGENT.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no {name} in {AGENT}")


def option(name: str) -> ast.expr:
    for node in ast.walk(ast.parse(AGENT.read_text())):
        if isinstance(node, ast.keyword) and node.arg == name:
            return node.value
    raise AssertionError(f"no {name}= in {AGENT}")


def test_the_agent_is_the_sdk_chats_agent_with_the_open_issues_read():
    for name in ("FRAMING", "READS", "WRITES", "DOCS", "MODEL"):
        assert constant(name) == sdk_constant(name), name
    assert set(constant("READS")) | set(constant("WRITES")) == TOOLS
    assert set(constant("DOCS")) == DOC_TOOLS and set(constant("ISSUES")) == ISSUE_TOOLS
    allowed = ast.unparse(option("allowed_tools"))
    assert "for name in READS" in allowed and "for name in DOCS" in allowed and "for name in ISSUES" in allowed
    assert "WRITES" not in allowed  # a write is never pre-allowed: it goes to the bridge's confirm
    assert set(bridge.WRITE_LEADS) == set(constant("WRITES"))  # the bridge has words for each write, and no other


def test_a_teams_own_instructions_follow_the_framing_line():
    assert constant("INSTRUCTIONS_ENV") == "AGENTIC_ADMIN_INSTRUCTIONS"
    assert ast.unparse(option("system_prompt")).endswith("'append': self.framing}")
    source = AGENT.read_text()
    assert 'f"{FRAMING}\\n\\n{own}" if own else FRAMING' in source  # with none set, the framing line alone


def test_the_agent_loads_no_settings_or_connectors_and_forces_no_credential():
    assert ast.literal_eval(option("setting_sources")) == [] and ast.literal_eval(option("tools")) == ["Skill"]
    assert ast.literal_eval(option("env")) == {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
    assert "ANTHROPIC_API_KEY" not in AGENT.read_text()


def test_the_bridge_imports_no_sdk_and_names_the_credentials_the_docs_do():
    tree = ast.parse((TEAMS / "bridge.py").read_text())
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported <= {"__future__", "asyncio", "json", "logging", "os", "uuid", "collections", "dataclasses", "pathlib", "typing"}
    assert set(bridge.METERED_ENV) == {"CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                                       "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
