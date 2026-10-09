"""The hosts: the plugin (Claude Code and the Agent SDK load it), the Hermes
wiring in examples/hermes/ and the Agent SDK chat in examples/agent-sdk/.
Each reaches exactly the board server's eleven tools, and the knowledge
server's two where a team has docs, and each frames the agent with the
README's line, so every host frames it the same way. The SDK chat's reads
run unasked, as the README's Claude Code command pre-allows them, and they
are the tools the servers mark read-only. That command and the SDK chat
give the same built-ins, and no claude.ai connectors."""

import ast
import json
import re
import sys
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from knowledge.config import load
from server.config import load as load_board
from server.mcp_app import build
from server.service import Boards
from tests.test_docs import DOC_TOOLS
from tests.test_mcp_app import TOOLS
from tests.test_service import service

ROOT = Path(__file__).resolve().parents[1]
HERMES = ROOT / "examples" / "hermes"
SDK_CHAT = ROOT / "examples" / "agent-sdk" / "chat.py"
PLUGIN = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
KNOWLEDGE_EXAMPLE = ROOT / "examples" / "knowledge" / "confluence.example.toml"


def hermes_servers() -> dict[str, str]:
    """Each server's block under the fragment's mcp_servers, by name."""
    text = (HERMES / "config.fragment.yaml").read_text()
    section = re.search(r"^mcp_servers:\n(.*?)^\S", text, re.S | re.M)
    assert section, "no mcp_servers section"
    parts = re.split(r"^  (\w+):\n", section.group(1), flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def include(block: str) -> set[str]:
    found = re.search(r"include: \[([^\]]*)\]", block)
    assert found, "no tools.include list"
    return set(re.findall(r"[a-z_]+", found.group(1)))


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


def test_the_plugin_starts_both_servers_and_the_knowledge_one_is_optional():
    servers = PLUGIN["mcpServers"]
    assert set(servers) == {"board", "knowledge"}
    assert servers["board"]["args"][-3:] == ["-m", "server", "${AGENTIC_ADMIN_BOARD}"]
    # an unset variable fails a plugin server in Claude Code; `:-` makes it empty, which serves no tools
    assert servers["knowledge"]["args"][-5:] == ["-m", "knowledge", "serve", "--config", "${AGENTIC_ADMIN_KNOWLEDGE:-}"]


@pytest.mark.anyio
@pytest.mark.parametrize("docs", [str(KNOWLEDGE_EXAMPLE), ""])
async def test_the_plugins_knowledge_command_serves_the_docs_tools_or_none(docs):
    args = PLUGIN["mcpServers"]["knowledge"]["args"]
    args = [docs if a == "${AGENTIC_ADMIN_KNOWLEDGE:-}" else a for a in args[args.index("python") + 1:]]
    async with Client(StdioServerParameters(command=sys.executable, args=args, cwd=str(ROOT))) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert names == (DOC_TOOLS if docs else set())


def test_hermes_includes_exactly_each_servers_tools():
    servers = hermes_servers()
    assert set(servers) == {"board", "knowledge"}
    assert include(servers["board"]) == TOOLS
    assert include(servers["knowledge"]) == DOC_TOOLS
    assert "python, -m, knowledge, serve, --config," in servers["knowledge"]


def test_hermes_passes_the_knowledge_server_the_docs_configs_secrets():
    cfg = load(KNOWLEDGE_EXAMPLE)
    for env in (cfg.token_env, cfg.user_env):
        assert f"{env}: ${{{env}}}" in hermes_servers()["knowledge"]


def test_hermes_serves_every_board_in_a_directory_with_each_backends_secrets():
    board = hermes_servers()["board"]
    assert "python, -m, server, boards/]" in board  # one profile, every board (D43)
    for example in sorted((ROOT / "examples" / "boards").glob("*.example.toml")):
        conn = load_board(example).connection
        for env in filter(None, (conn.token_env, conn.user_env)):
            assert f"{env}: ${{{env}}}" in board, f"{example.name} needs {env}"


def test_hermes_platforms_reach_both_servers_and_nothing_else():
    text = (HERMES / "config.fragment.yaml").read_text()
    platforms = re.findall(r"^  (\w+): \[([^\]]*)\]", re.search(r"^platform_toolsets:\n((?:  .*\n)+)", text, re.M)
                           .group(1), re.M)
    assert platforms and all(sets.split(", ") == ["clarify", "skills", "board", "knowledge"] for _, sets in platforms)


def test_hermes_soul_is_the_readme_framing_line():
    line = (HERMES / "SOUL.md").read_text().strip()
    assert f'--append-system-prompt "{line}"' in (ROOT / "README.md").read_text()


def test_sdk_chat_frames_like_the_readme_and_hermes():
    assert sdk_constant("FRAMING") == (HERMES / "SOUL.md").read_text().strip()


@pytest.mark.anyio
async def test_sdk_chat_asks_before_exactly_the_server_writes():
    svc, _, _ = service()
    async with Client(build(Boards([svc]))) as client:
        tools = (await client.list_tools()).tools
    reads = {tool.name for tool in tools if tool.annotations.read_only_hint}
    assert set(sdk_constant("READS")) == reads
    assert set(sdk_constant("WRITES")) == TOOLS - reads


def test_sdk_chat_allows_the_docs_tools_which_are_all_reads():
    assert set(sdk_constant("DOCS")) == DOC_TOOLS  # tests/test_docs.py checks they are read-only
    assert "DOCS_PREFIX + name for name in DOCS" in ast.unparse(sdk_option("allowed_tools"))


def test_readme_pre_allows_the_sdk_chats_reads():
    allowed = re.search(r'--allowedTools "([^"]*)"', (ROOT / "README.md").read_text())
    assert allowed, "no --allowedTools in the README"
    assert set(re.findall(r"\$\{T\}([a-z_]+)", allowed.group(1))) == set(sdk_constant("READS"))
    assert set(re.findall(r"\$\{K\}([a-z_]+)", allowed.group(1))) == set(sdk_constant("DOCS"))
    assert "K=mcp__plugin_agentic-administration_knowledge__" in (ROOT / "README.md").read_text()


def test_readme_gives_claude_code_the_sdk_chats_built_in_tools():
    tools = re.search(r"--tools (\S+)", (ROOT / "README.md").read_text())
    assert tools, "no --tools in the README"
    assert tools.group(1).split(",") == ast.literal_eval(sdk_option("tools")) == ["Skill"]


def test_readme_keeps_claude_codes_prompt_before_a_write():
    # the SDK chat asks through can_use_tool; a requester's default auto mode would skip Claude Code's prompt
    assert "--tools Skill --permission-mode manual" in (ROOT / "README.md").read_text()
    assert sdk_option("can_use_tool")


def test_neither_claude_host_loads_claude_ai_connectors():
    env = sdk_option("env")
    assert isinstance(env, ast.Dict), "the SDK chat's env= is not a dict literal"
    values = {ast.literal_eval(k): v for k, v in zip(env.keys, env.values)}
    assert ast.literal_eval(values["ENABLE_CLAUDEAI_MCP_SERVERS"]) == "false"
    assert "ENABLE_CLAUDEAI_MCP_SERVERS=false claude --plugin-dir" in (ROOT / "README.md").read_text()
