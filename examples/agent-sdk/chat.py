"""A terminal chat with the backlog agent, on the Claude Agent SDK (roadmap/14 D6).

It loads this repo as a plugin, as `claude --plugin-dir` does: the skills
plus the board's MCP server, framed by the README's line. The session gets
the board's eleven tools and the Skill tool, nothing else: no shell, files,
web or memory, and no user or project settings. Reads run without asking;
each write waits for a y here, a second guard beside the skill's own yes.

    export AGENTIC_ADMIN_BOARD=boards/<board>.toml   # plus the board's token env
    export ANTHROPIC_API_KEY=...                     # or ANTHROPIC_API_KEY_BW_ITEM
    uv run --group agent-sdk python examples/agent-sdk/chat.py

Ctrl-D ends the chat. The session id printed at the start names its
transcript under ~/.claude/projects/.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import tempfile
import threading
import uuid
import warnings
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    TextBlock,
    ToolPermissionContext,
)

from server.secrets import SecretUnavailable, get

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["name"]
TOOL_PREFIX = f"mcp__plugin_{PLUGIN}_board__"  # how Claude Code names a plugin server's tools
MODEL = "claude-opus-5-5"  # the Phase 3 and 4 gates' model

# The README's framing line; examples/hermes/SOUL.md holds the same one.
FRAMING = (
    "You are a team's backlog assistant. Every request is about the team's board, "
    "never something to build or design here. New work starts with the intake skill, "
    "ending or planning a sprint with plan-sprint, and reviewing what's waiting with groom."
)
# The server's eleven tools: reads run without asking, writes wait for a y.
READS = ("describe_board", "find_items", "get_item", "get_iteration", "propose_item")
WRITES = ("commit_item", "update_item", "add_comment", "create_iteration",
          "move_to_iteration", "close_iteration")
# The SDK warns that allowed reads skip ask_before_write; that is the point.
warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)


async def ask(prompt: str) -> str | None:
    """input() on a daemon thread, None at end of input. A Ctrl-C mid-read then
    exits at once; asyncio.to_thread's worker would hold the exit until Enter."""
    loop = asyncio.get_running_loop()
    answer: asyncio.Future[str | None] = loop.create_future()

    def read() -> None:
        try:
            line = input(prompt)
        except EOFError:
            line = None
        with contextlib.suppress(RuntimeError):  # the chat ended while this read waited
            loop.call_soon_threadsafe(lambda: answer.done() or answer.set_result(line))

    threading.Thread(target=read, daemon=True).start()
    return await answer


async def ask_before_write(tool: str, args: dict[str, Any], context: ToolPermissionContext):
    name = tool.removeprefix(TOOL_PREFIX)
    if name not in WRITES:
        return PermissionResultDeny(message=f"{tool} is not one of the board's tools")
    answer = await ask(f"\nAllow {name} {json.dumps(args)}? [y/N] ")
    if (answer or "").strip().lower() in ("y", "yes"):
        return PermissionResultAllow()
    return PermissionResultDeny(message="the user said no")


def options(cwd: str, api_key: str, session_id: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=MODEL,
        cwd=cwd,
        session_id=session_id,
        env={"ANTHROPIC_API_KEY": api_key},
        plugins=[{"type": "local", "path": str(ROOT)}],
        system_prompt={"type": "preset", "preset": "claude_code", "append": FRAMING},
        setting_sources=[],  # no user or project settings, hooks or CLAUDE.md
        tools=["Skill"],  # the only built-in; the board's tools come from the plugin
        skills=[f"{PLUGIN}:{p.parent.name}" for p in sorted((ROOT / "skills").glob("*/SKILL.md"))],
        allowed_tools=[TOOL_PREFIX + name for name in READS],
        can_use_tool=ask_before_write,
    )


async def chat(opts: ClaudeAgentOptions) -> None:
    async with ClaudeSDKClient(opts) as client:
        while True:
            prompt = await ask("\n> ")
            if prompt is None:
                return
            if not prompt.strip():
                continue
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(block.text)


def main() -> int:
    if not os.environ.get("AGENTIC_ADMIN_BOARD"):
        print("Set AGENTIC_ADMIN_BOARD to the board's TOML config.", file=sys.stderr)
        return 2
    try:
        # A metered API key, never a claude.ai login (the Agent SDK's terms).
        api_key = get("ANTHROPIC_API_KEY")
    except SecretUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2
    session_id = str(uuid.uuid4())
    print(f"session {session_id}", file=sys.stderr)
    # An empty working directory, as for `claude --plugin-dir`: no repo context.
    with tempfile.TemporaryDirectory() as empty:
        try:
            asyncio.run(chat(options(empty, api_key, session_id)))
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
