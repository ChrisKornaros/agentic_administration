"""The host examples: the Hermes wiring in examples/hermes/ and the Agent SDK
chat in examples/agent-sdk/. Each reaches exactly the server's eleven tools,
and each frames the agent with the README's line, so every host frames it
the same way. The SDK chat's reads run unasked, as the README's Claude Code
command pre-allows them, and they are the tools the server marks read-only."""

import ast
import re
from pathlib import Path

import pytest
from mcp import Client

from server.mcp_app import build
from tests.test_mcp_app import TOOLS
from tests.test_service import service

ROOT = Path(__file__).resolve().parents[1]
HERMES = ROOT / "examples" / "hermes"
SDK_CHAT = ROOT / "examples" / "agent-sdk" / "chat.py"


def sdk_constant(name: str):
    """A literal from chat.py, read without importing it: the SDK is an optional group."""
    for node in ast.parse(SDK_CHAT.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no {name} in {SDK_CHAT}")


def sdk_option(name: str) -> ast.expr:
    """The expression chat.py passes to ClaudeAgentOptions as `name`."""
    for node in ast.walk(ast.parse(SDK_CHAT.read_text())):
        if isinstance(node, ast.keyword) and node.arg == name:
            return node.value
    raise AssertionError(f"no {name}= in {SDK_CHAT}")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_hermes_includes_exactly_the_server_tools():
    text = (HERMES / "config.fragment.yaml").read_text()
    include = re.search(r"include: \[([^\]]*)\]", text)
    assert include, "no tools.include list"
    assert set(re.findall(r"[a-z_]+", include.group(1))) == TOOLS


def test_hermes_soul_is_the_readme_framing_line():
    line = (HERMES / "SOUL.md").read_text().strip()
    assert f'--append-system-prompt "{line}"' in (ROOT / "README.md").read_text()


def test_sdk_chat_frames_like_the_readme_and_hermes():
    assert sdk_constant("FRAMING") == (HERMES / "SOUL.md").read_text().strip()


@pytest.mark.anyio
async def test_sdk_chat_asks_before_exactly_the_server_writes():
    svc, _, _ = service()
    async with Client(build(svc)) as client:
        tools = (await client.list_tools()).tools
    reads = {tool.name for tool in tools if tool.annotations.read_only_hint}
    assert set(sdk_constant("READS")) == reads
    assert set(sdk_constant("WRITES")) == TOOLS - reads


def test_readme_pre_allows_the_sdk_chats_reads():
    allowed = re.search(r'--allowedTools "([^"]*)"', (ROOT / "README.md").read_text())
    assert allowed, "no --allowedTools in the README"
    assert set(re.findall(r"\$\{T\}([a-z_]+)", allowed.group(1))) == set(sdk_constant("READS"))


def test_readme_gives_claude_code_the_sdk_chats_built_in_tools():
    tools = re.search(r"--tools (\S+)", (ROOT / "README.md").read_text())
    assert tools, "no --tools in the README"
    assert tools.group(1).split(",") == ast.literal_eval(sdk_option("tools")) == ["Skill"]
