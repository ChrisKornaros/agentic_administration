"""The backlog agent in Microsoft Teams: a thin bot over `bridge.py`, on
Microsoft's Teams SDK for Python (`microsoft-teams-apps`).

All it knows is Teams. Each direct message goes to `Bridge.handle` with the
sender's Entra object id, the chat as the conversation and the activity's id
(Teams may deliver one twice). The bridge does the rest: who is served, one
session a chat, `/new`, and the yes before a write.

**Teams waits 25 seconds for an answer and a turn takes longer**, so the
handler never waits for the agent. It starts the turn as a task and
returns; when the turn begins the bot posts "Working on it…", and the
agent's first words replace that message. Anything after is a new message.

**Direct chats only, for now.** In a channel or a group chat Teams
delivers only the messages that @mention the bot, so a typed "yes" would
never arrive. There the bot says so and does nothing else.

**Who it is for** comes from the environment, never from this file:

  TEAMS_OWNER     the owner's Entra object id. With none set the bot serves
                  nobody, and tells each sender their own id so it can be set.
  TEAMS_ALLOWED   more object ids, comma-separated; served only on metered
                  billing (`bridge.py`: on a Claude plan login, the owner alone)
  TENANT_ID       with it set, a message from any other tenant is dropped
  CLIENT_ID, CLIENT_SECRET, TENANT_ID   the bot's own registration, read by
                  the SDK; the secret may come from Bitwarden through
                  `CLIENT_SECRET_BW_ITEM` (server/secrets.py)

    export AGENTIC_ADMIN_BOARD=boards/<board>.toml   # or boards/; plus each board's token env
    uv run --group teams --group agent-sdk python examples/teams/bot.py --playground   # no tenant: Agents Playground
    uv run --group teams --group agent-sdk python examples/teams/bot.py --socket       # real Teams, no public endpoint
    uv run --group teams --group agent-sdk python examples/teams/bot.py                # real Teams, HTTPS on --port

`--playground` accepts requests nobody signed, so it is for a laptop and
Microsoft's Agents Playground only: it listens on 127.0.0.1 alone and
refuses to start beside a CLIENT_ID.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from microsoft_teams.api import MessageActivity, MessageActivityInput
from microsoft_teams.apps import ActivityContext, App

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bridge import Bridge, Sessions  # noqa: E402

log = logging.getLogger("agentic_administration.teams")

WORKING = "Working on it…"
DIRECT_ONLY = "I only work in a direct chat for now. Message me one to one."
NO_OWNER = ("This assistant has no owner set yet, so it works with nobody. Your id here is `{sender}`: "
            "whoever runs it sets TEAMS_OWNER to the owner's id and restarts it.")
PIECE = 12_000  # characters a message; Teams refuses a message near 100 KB
TEXT_FORMAT = "extendedmarkdown"  # fenced code and tables, which the skills' previews use


def pieces(text: str, size: int = PIECE) -> list[str]:
    """`text` as messages of at most `size` characters, cut at a blank line where there is one."""
    out: list[str] = []
    while len(text) > size:
        cut = text.rfind("\n\n", 0, size)
        cut = cut if cut > size // 2 else size
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return out + [text] if text else out


class Reply:
    """One turn's answers in a chat: "Working on it…", then the agent's words in its place."""

    def __init__(self, ctx: ActivityContext[MessageActivity]) -> None:
        self._ctx, self._working = ctx, None

    async def working(self) -> None:
        self._working = (await self._ctx.send(WORKING)).id

    async def say(self, text: str) -> None:
        for piece in pieces(text):
            message = MessageActivityInput(text=piece).with_text_format(TEXT_FORMAT)
            placeholder, self._working = self._working, None
            if placeholder:
                try:
                    await self._ctx.send(MessageActivityInput(text=piece).with_text_format(TEXT_FORMAT).with_id(placeholder))
                    continue
                except Exception:  # an edit Teams refuses must not lose the answer
                    log.warning("could not edit the placeholder; sending a new message", exc_info=True)
            await self._ctx.send(message)


def build(bridge: Bridge | None, *, tenant: str | None = None, **options: Any) -> tuple[App, set[asyncio.Task[None]]]:
    """The Teams app, and the set its running turns are kept in. With no
    `bridge` (no owner set) it serves nobody."""
    app = App(**options)
    turns: set[asyncio.Task[None]] = set()

    def done(task: asyncio.Task[None]) -> None:
        turns.discard(task)
        if not task.cancelled() and task.exception():
            log.error("a turn's task failed", exc_info=task.exception())

    @app.on_message
    async def on_message(ctx: ActivityContext[MessageActivity]) -> None:
        activity = ctx.activity
        chat = activity.conversation
        if tenant and chat.tenant_id != tenant:
            log.warning("dropped a message from another tenant")
            return
        if chat.conversation_type != "personal":
            await ctx.send(DIRECT_ONLY)
            return
        sender = activity.from_.aad_object_id or activity.from_.id
        if bridge is None:
            await ctx.send(NO_OWNER.format(sender=sender))
            return
        reply = Reply(ctx)
        # Teams waits 25 s for this handler; the turn runs on after it returns.
        task = asyncio.create_task(bridge.handle(
            sender, f"{chat.tenant_id or 'no-tenant'}:{chat.id}", activity.text or "", reply.say,
            message_id=activity.id, started=reply.working))
        turns.add(task)
        task.add_done_callback(done)

    return app, turns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bot.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", default=str(Path.home() / ".cache" / "agentic-administration" / "teams"),
                        help="where the sessions file and the agent's working directory go")
    parser.add_argument("--port", type=int, default=3978, help="the port /api/messages is served on (default 3978)")
    how = parser.add_mutually_exclusive_group()
    how.add_argument("--playground", action="store_true", help="accept unsigned requests, for Agents Playground on a laptop")
    how.add_argument("--socket", action="store_true", help="socket mode: the bot dials out, so it needs no public endpoint")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    options: dict[str, Any] = {}
    if args.playground:
        if os.environ.get("CLIENT_ID"):
            parser.error("--playground accepts unsigned requests: it will not start with CLIENT_ID set")
        import uvicorn
        from microsoft_teams.apps import FastAPIAdapter

        options["dangerously_allow_unauthenticated_requests"] = True
        # Unsigned requests are accepted, so listen on this machine only (the SDK's default is every interface).
        options["http_server_adapter"] = FastAPIAdapter(server_factory=lambda fastapi: uvicorn.Server(
            uvicorn.Config(app=fastapi, host="127.0.0.1", port=args.port, log_level="info")))
    else:
        from server import secrets  # the one secret boundary

        try:
            options["client_secret"] = secrets.get("CLIENT_SECRET")
        except secrets.SecretUnavailable:
            pass  # a managed identity or a token provider: the SDK reads what it needs
    if args.socket:
        options["socket_mode"] = True

    owner = os.environ.get("TEAMS_OWNER", "").strip()
    bridge = None
    if owner:
        from agent import ClaudeAgent  # the Agent SDK is needed only to run turns

        state = Path(args.state)
        allowed = [a.strip() for a in os.environ.get("TEAMS_ALLOWED", "").split(",") if a.strip()]
        bridge = Bridge(ClaudeAgent(state / "cwd"), Sessions(state / "sessions.json"), owner=owner, allowed=allowed)
        log.info("billing: %s; serving %d %s", bridge.mode, len(bridge.permitted),
                 "person" if len(bridge.permitted) == 1 else "people")
        if bridge.mode == "plan" and allowed:
            log.warning("on a Claude plan login only the owner is served: TEAMS_ALLOWED is ignored until billing is metered")
    else:
        log.warning("TEAMS_OWNER is not set: the bot serves nobody and tells each sender their id")

    app, _ = build(bridge, tenant=os.environ.get("TENANT_ID") or None, **options)
    try:
        asyncio.run(app.start(args.port))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # `server.secrets`, when run as a script
    sys.exit(main())
