"""The MCP layer: the tool surface over the SDK's in-process client (both
handshakes) and the real stdio entry point. Offline: the in-process tests
use the fake Plane transport, and the stdio test only lists tools, which
never reaches the tracker."""

import sys
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from server.mcp_app import build
from server.service import Boards
from tests.test_intake import SPLIT
from tests.test_plane_adapter import CONFIG
from tests.test_service import service

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "describe_board", "find_items", "get_item", "get_iteration", "propose_item", "commit_item",
    "update_item", "add_comment", "create_iteration", "move_to_iteration", "close_iteration",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def check_surface(tools) -> None:
    assert {tool.name for tool in tools} == TOOLS
    for tool in tools:
        assert "delete" not in tool.name
        assert tool.annotations.read_only_hint or tool.annotations.destructive_hint is False


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_exactly_the_eleven_tools_and_none_deletes(mode):
    svc, _, _ = service()
    async with Client(build(Boards([svc])), mode=mode) as client:
        check_surface((await client.list_tools()).tools)


@pytest.mark.anyio
async def test_propose_then_commit_over_mcp():
    svc, _, _ = service()
    async with Client(build(Boards([svc]))) as client:
        proposed = await client.call_tool("propose_item", {"intake_id": "req-0010", "level": "epic", "title": "Chat Intake"})
        assert not proposed.is_error
        committed = await client.call_tool("commit_item", {"token": proposed.structured_content["token"]})
    assert not committed.is_error
    assert committed.structured_content["item"]["title"] == "Chat Intake"
    assert committed.structured_content["item"]["labels"] == ["needs-review"]
    assert committed.structured_content["already_existed"] is False


@pytest.mark.anyio
async def test_propose_from_an_intake_record_over_mcp():
    story = {**SPLIT["parts"][1], "placement": {"parent": "AA-1"}}
    svc, _, _ = service()
    async with Client(build(Boards([svc]))) as client:
        [tool] = [t for t in (await client.list_tools()).tools if t.name == "propose_item"]
        out = await client.call_tool("propose_item", {"intake": {**SPLIT, "parts": [story]}, "part": "csv"})
    assert set(tool.input_schema["$defs"]["Criterion"]["required"]) == {"given", "when", "then"}
    assert not out.is_error
    preview = out.structured_content["preview"]
    assert preview["parent"]["key"] == "AA-1" and "1. **Given** a saved report" in preview["description"]


@pytest.mark.anyio
async def test_failures_reach_the_agent_as_actionable_errors():
    svc, _, _ = service(config={**CONFIG, "labels": {"review": "review-me"}})
    async with Client(build(Boards([svc]))) as client:
        mismatch = await client.call_tool("propose_item", {"intake_id": "r-1", "level": "epic", "title": "X"})
        unknown = await client.call_tool("commit_item", {"token": "nope"})
        bad_level = await client.call_tool("propose_item", {"intake_id": "r-1", "level": "saga", "title": "X"})
    assert mismatch.is_error and "Fix the board config" in mismatch.content[0].text
    assert unknown.is_error and "propose_item again" in unknown.content[0].text
    assert bad_level.is_error


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_the_stdio_entry_point_serves_the_tools(mode):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "server", str(ROOT / "examples" / "boards" / "plane.example.toml")],
        cwd=str(ROOT),
    )
    async with Client(params, mode=mode) as client:
        check_surface((await client.list_tools()).tools)


@pytest.mark.anyio
async def test_the_stdio_entry_point_serves_a_directory_of_boards():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "server", str(ROOT / "examples" / "boards")], cwd=str(ROOT),
    )
    async with Client(params) as client:
        listed = await client.call_tool("describe_board", {})  # from the configs: no tracker, no token
    names = [b["board"] for b in listed.structured_content["boards"]]
    assert names == ["calendar.example", "jira.example", "plane.example"]


@pytest.mark.anyio
async def test_every_tool_takes_the_board_and_two_boards_stay_apart():
    from tests.test_service import two_boards

    boards, _, _ = two_boards()
    async with Client(build(boards)) as client:
        tools = (await client.list_tools()).tools
        unnamed = await client.call_tool("find_items", {})
        proposed = await client.call_tool("propose_item", {"intake_id": "20261009-post", "level": "story",
                                                           "title": "Loaves Of The Week", "board": "content"})
        crossed = await client.call_tool("commit_item", {"token": proposed.structured_content["token"], "board": "web"})
        committed = await client.call_tool("commit_item", {"token": proposed.structured_content["token"],
                                                           "board": "content"})
    assert all("board" in t.input_schema["properties"] and "board" not in t.input_schema.get("required", [])
               for t in tools)
    assert unnamed.is_error and "pass board" in unnamed.content[0].text
    assert proposed.structured_content["board"] == "content"
    assert crossed.is_error and "nothing was written" in crossed.content[0].text
    assert committed.structured_content["board"] == "content"


@pytest.mark.anyio
async def test_dates_and_fields_over_mcp():
    from tests.test_service import fields_service

    svc, _, _ = fields_service()
    async with Client(build(Boards([svc]))) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        out = await client.call_tool("propose_item", {
            "intake_id": "req-0011", "level": "story", "title": "Loaves Of The Week", "target_date": "2026-10-05",
            "fields": {"published": True, "channels": ["Web"]}})
    for name in ("propose_item", "update_item"):
        assert {"start_date", "target_date", "fields"} <= set(tools[name].input_schema["properties"])
    assert not out.is_error
    assert out.structured_content["preview"]["fields"] == {"published": True, "channels": ["Web"]}


@pytest.mark.anyio
async def test_a_template_over_mcp():
    from tests.test_service import TEMPLATES, fields_service

    svc, _, _ = fields_service(templates=TEMPLATES)
    async with Client(build(Boards([svc]))) as client:
        [tool] = [t for t in (await client.list_tools()).tools if t.name == "propose_item"]
        out = await client.call_tool("propose_item", {"intake_id": "202611-content", "template": "cycle",
                                                      "start_date": "2026-11-01"})
        board = await client.call_tool("describe_board", {})
    assert "template" in tool.input_schema["properties"] and not out.is_error
    assert out.structured_content["preview"]["title"] == "November 2026 Content"
    assert set(board.structured_content["templates"]) == {"cycle", "post", "fixed"}
