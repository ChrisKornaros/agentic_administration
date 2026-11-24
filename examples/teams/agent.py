"""The bridge's agent: one turn of the backlog agent on the Claude Agent SDK.

The same session `examples/agent-sdk/chat.py` builds (this repo as a
plugin, the framing line, the Skill tool plus the board's eleven tools and
the docs' two, no user or project settings, no claude.ai connectors), with
three differences a chat bridge needs:

- **A turn at a time.** Each call starts the SDK, runs one turn and ends:
  the first with `session_id`, each later one with `resume`. Nothing stays
  running between messages, so a restart loses nothing.
- **The open-issues tool is allowed** where the plugin serves it. It reads.
- **No credential is forced.** The SDK inherits the process's environment:
  a metered key or a cloud provider when one is set, otherwise the Claude
  plan login of whoever started the process. `bridge.billing()` reads the
  same environment and the bridge then serves the owner alone.

Reads run without asking. A write goes to the bridge's `confirm`, and
anything else is refused: the session has no shell, files or web.
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping

from claude_agent_sdk import (
    AssistantMessage,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
)

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["name"]
TOOL_PREFIX = f"mcp__plugin_{PLUGIN}_board__"
DOCS_PREFIX = f"mcp__plugin_{PLUGIN}_knowledge__"
ISSUES_PREFIX = f"mcp__plugin_{PLUGIN}_issues__"
MODEL = "claude-opus-5-5"  # AGENTIC_ADMIN_MODEL overrides it, e.g. with a Foundry deployment's name

# The README's framing line; examples/agent-sdk/chat.py and examples/hermes/SOUL.md hold the same one.
FRAMING = (
    "You are a team's backlog assistant. Every request is about one of the team's boards, "
    "never something to build or design here. New work starts with the intake skill, "
    "ending or planning a sprint with plan-sprint, planning a month or cycle of dated work "
    "from the board's templates with plan-cycle, and reviewing what's waiting with groom."
)
INSTRUCTIONS_ENV = "AGENTIC_ADMIN_INSTRUCTIONS"  # a team's own rules for the assistant, added after the framing line
READS = ("describe_board", "find_items", "get_item", "get_iteration", "propose_item")
WRITES = ("commit_item", "update_item", "add_comment", "create_iteration",
          "move_to_iteration", "close_iteration")
DOCS = ("search_docs", "get_doc")
ISSUES = ("find_open_issues",)

Confirm = Callable[[str, Mapping[str, Any]], Awaitable[bool]]
# The SDK warns that allowed reads skip the write guard; that is the point.
warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)


class AgentFailed(RuntimeError):
    """The turn ended in an error the SDK reported."""


class ClaudeAgent:
    """`bridge.Agent` over the Claude Agent SDK. `cwd` is an empty directory
    the sessions are filed under; keep it the same from run to run."""

    def __init__(self, cwd: str | Path, *, model: str | None = None) -> None:
        self.cwd = Path(cwd)
        self.model = model or os.environ.get("AGENTIC_ADMIN_MODEL") or MODEL
        own = os.environ.get(INSTRUCTIONS_ENV, "").strip()
        self.framing = f"{FRAMING}\n\n{own}" if own else FRAMING

    def options(self, session_id: str, resume: bool, confirm: Confirm) -> ClaudeAgentOptions:
        async def ask_before_write(tool: str, args: dict[str, Any], context: ToolPermissionContext):
            name = tool.removeprefix(TOOL_PREFIX)
            if tool == name or name not in WRITES:
                return PermissionResultDeny(message=f"{tool} is not one of the board's tools")
            if await confirm(name, args):
                return PermissionResultAllow()
            return PermissionResultDeny(message="the user said no")

        return ClaudeAgentOptions(
            model=self.model,
            cwd=str(self.cwd),
            session_id=None if resume else session_id,
            resume=session_id if resume else None,
            env={"ENABLE_CLAUDEAI_MCP_SERVERS": "false"},  # merged over the inherited environment
            plugins=[{"type": "local", "path": str(ROOT)}],
            system_prompt={"type": "preset", "preset": "claude_code", "append": self.framing},
            setting_sources=[],  # no user or project settings, hooks or CLAUDE.md
            tools=["Skill"],  # the only built-in; the board's tools come from the plugin
            skills=[f"{PLUGIN}:{p.parent.name}" for p in sorted((ROOT / "skills").glob("*/SKILL.md"))],
            allowed_tools=([TOOL_PREFIX + name for name in READS] + [DOCS_PREFIX + name for name in DOCS]
                           + [ISSUES_PREFIX + name for name in ISSUES]),
            can_use_tool=ask_before_write,
        )

    async def run(self, session_id: str, resume: bool, text: str, confirm: Confirm) -> AsyncIterator[str]:
        self.cwd.mkdir(parents=True, exist_ok=True)
        async with ClaudeSDKClient(self.options(session_id, resume, confirm)) as client:
            await client.query(text)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    said = "\n\n".join(b.text for b in message.content if isinstance(b, TextBlock) and b.text.strip())
                    if said:
                        yield said
                elif isinstance(message, ResultMessage) and message.is_error:
                    raise AgentFailed(str(message.result or message.subtype))
