"""The chat bridge: one chat conversation to one agent session, with no
chat platform and no agent SDK in it.

A chat host (the Teams bot beside this file, or `terminal.py` for a run
with no Teams at all) hands every incoming message to `Bridge.handle`,
with who sent it, which conversation it is in and a way to answer. The
bridge decides what the message is:

- from someone it may not serve: a refusal, and nothing reaches the agent;
- the answer to a write the agent is waiting to make: a yes or a no;
- `/new`: the conversation starts over with a fresh session;
- anything else: the next turn of that conversation's session.

**One conversation, one session.** The first message starts a session and
each later one resumes it, so the agent keeps the thread across restarts:
`Sessions` is a small JSON file. Turns in one conversation run one at a
time, in the order they arrived; different conversations run side by side.

**Each write waits for a yes.** When the agent asks to use a write tool,
the bridge posts what it wants to do and holds the turn until the person
who sent that turn answers. Only "yes" allows it. No answer in ten minutes
is a no. This is the host's own guard, beside the skill's.

**Whose usage pays.** `billing()` reads the environment. With a metered
credential there (an API key, or Foundry, Bedrock or Vertex switched on),
the people on the allow-list are served. With none, turns run on the
Claude plan login of whoever started the process, and a plan seat is that
one person's: the bridge then serves the owner alone, whatever the
allow-list says.

Standard library only, so the offline tests run it against a fake agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Mapping, Protocol

log = logging.getLogger("agentic_administration.bridge")

# A credential here means the turns are billed by use, not to a person's plan.
METERED_ENV = ("CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
               "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
YES = ("y", "yes")
NEW = ("/new", "new conversation")
CONFIRM_TIMEOUT = 600.0  # seconds a write waits for its yes
SEEN = 500  # message ids remembered, to drop a redelivery
ARGS_SHOWN = 1500  # characters of a write's details shown before they are cut

REFUSED = "I'm not set up to work with you here. Ask whoever runs this assistant to add you."
REFUSED_ON_A_PLAN = ("I'm running on one person's Claude plan for now, so I can only work with them. "
                     "Ask whoever runs this assistant to move it to metered billing.")
STARTED_OVER = "Started a new conversation. I no longer have the earlier one in view."
NOT_YOURS = "That yes or no has to come from the person who asked for the change."
NO_ANSWER = "No answer, so nothing was written. Ask again when you're ready."
FAILED = "Something went wrong on my side and that turn did not finish. Nothing more was written. Try again in a moment."

Say = Callable[[str], Awaitable[None]]
Confirm = Callable[[str, Mapping[str, Any]], Awaitable[bool]]


class Agent(Protocol):
    def run(self, session_id: str, resume: bool, text: str, confirm: Confirm) -> AsyncIterator[str]:
        """One turn: start session `session_id`, or resume it, with `text`.
        Yields the agent's text as it comes; awaits `confirm(tool, arguments)`
        before each write and makes the write only on True."""
        ...


def billing(environ: Mapping[str, str] | None = None) -> str:
    """`metered` when the environment carries a pay-by-use credential, else `plan`."""
    env = os.environ if environ is None else environ
    on = lambda value: value.strip().lower() not in ("", "0", "false")  # noqa: E731
    return "metered" if any(on(env.get(name, "")) for name in METERED_ENV) else "plan"


class Sessions:
    """Conversation key -> session id, kept in one JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._ids: dict[str, str] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text() or "{}")
            self._ids = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def get(self, conversation: str) -> str | None:
        return self._ids.get(conversation)

    def set(self, conversation: str, session_id: str) -> None:
        self._ids[conversation] = session_id
        self._save()

    def drop(self, conversation: str) -> None:
        if self._ids.pop(conversation, None) is not None:
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._ids, indent=2, sort_keys=True))
        os.replace(tmp, self.path)  # a crash leaves the old file or the new one, never half of one


@dataclass
class _Pending:
    sender: str
    answer: asyncio.Future[bool]


# What each board write does, in words, and the arguments those words already show.
WRITE_LEADS: dict[str, tuple[str, tuple[str, ...]]] = {
    "commit_item": ("create the item I just previewed", ("token",)),  # the token says nothing to a person
    "update_item": ("update **{ref}**", ("ref",)),
    "add_comment": ("add a comment to **{ref}**", ("ref",)),
    "create_iteration": ("create the iteration **{name}**", ("name",)),
    "move_to_iteration": ("move {items} into the iteration **{iteration}**", ("items", "iteration")),
    "close_iteration": ("close the iteration **{iteration}**", ("iteration",)),
}
LABELS = {"body": "Comment"}  # an argument's name as a person reads it, where its own name would not do
REPLACED = ("labels", "assignees")  # update_item replaces the whole set with what it is given
QUOTED = ("body", "description")  # shown as a quote under their name, as is any long text
LONG = 80


def _plain(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Mapping):
        return ", ".join(f"{k}: {_plain(v)}" for k, v in value.items()) or "none"
    if isinstance(value, (list, tuple)):
        return ", ".join(_plain(v) for v in value) or "none"
    return str(value) or "(empty)"


def write_request(tool: str, arguments: Mapping[str, Any]) -> str:
    """What a write is about to do, in words a person can check before saying yes."""
    args = {name: value for name, value in arguments.items() if value is not None}
    board = args.pop("board", None)
    lead, shown = WRITE_LEADS.get(tool, ("", ()))
    if lead and all(name in args for name in shown):
        lead = lead.format(**{name: _plain(args.pop(name)) for name in shown})
    else:  # a tool this table does not know, or a call without the arguments its words need
        lead = f"run **{tool}**"
    fields: list[str] = []
    quotes: list[str] = []
    for name, value in args.items():
        label = LABELS.get(name, name.replace("_", " ").capitalize())
        if name in REPLACED:
            label += " (replacing the current ones)"
        text = _plain(value)
        if isinstance(value, str) and (name in QUOTED or len(text) > LONG or "\n" in text):
            quotes.append(f"**{label}:**\n\n" + "\n".join(f"> {line}" for line in text.splitlines()))
        else:
            fields.append(f"- **{label}:** {text}")
    details = "\n\n".join(["\n".join(fields)] * bool(fields) + quotes)
    if len(details) > ARGS_SHOWN:
        details = details[:ARGS_SHOWN] + "\n\n… (cut)"
    head = f"I'm about to {lead}" + (f" on the **{board}** board" if board else "")
    ask = "Reply **yes** to let it through. Anything else stops it."
    return f"{head}:\n\n{details}\n\n{ask}" if details else f"{head}.\n\n{ask}"


class Bridge:
    def __init__(self, agent: Agent, sessions: Sessions, *, owner: str, allowed: Iterable[str] = (),
                 mode: str | None = None, confirm_timeout: float = CONFIRM_TIMEOUT) -> None:
        self.agent, self.sessions, self.owner = agent, sessions, owner
        self.mode = billing() if mode is None else mode
        # A plan seat is one person's: on a plan login the allow-list is cut to the owner.
        self.permitted = frozenset({owner}) if self.mode == "plan" else frozenset({owner, *allowed})
        self.confirm_timeout = confirm_timeout
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending: dict[str, _Pending] = {}
        self._seen: OrderedDict[str, None] = OrderedDict()

    def busy(self, conversation: str) -> bool:
        """A turn is running in this conversation."""
        lock = self._locks.get(conversation)
        return bool(lock and lock.locked())

    def waiting(self, conversation: str) -> bool:
        """A write in this conversation is waiting for its yes or no."""
        pending = self._pending.get(conversation)
        return bool(pending and not pending.answer.done())

    def _redelivered(self, message_id: str | None) -> bool:
        if message_id is None:
            return False
        if message_id in self._seen:
            return True
        self._seen[message_id] = None
        while len(self._seen) > SEEN:
            self._seen.popitem(last=False)
        return False

    async def handle(self, sender: str, conversation: str, text: str, say: Say, *, message_id: str | None = None,
                     started: Callable[[], Awaitable[None]] | None = None) -> None:
        """One incoming message. `say` posts a message back to the conversation.
        `started` is awaited when the message begins a turn, and only then: a
        host uses it to show that work is under way."""
        if self._redelivered(message_id):
            return
        if sender not in self.permitted:
            await say(REFUSED_ON_A_PLAN if self.mode == "plan" else REFUSED)
            return
        text = text.strip()
        if not text:
            return
        if self.waiting(conversation):
            pending = self._pending[conversation]
            if sender != pending.sender:
                await say(NOT_YOURS)
                return
            pending.answer.set_result(text.lower() in YES)
            return
        if text.lower() in NEW:
            self.sessions.drop(conversation)
            await say(STARTED_OVER)
            return
        async with self._locks.setdefault(conversation, asyncio.Lock()):
            if started:
                await started()
            await self._turn(sender, conversation, text, say)

    async def _turn(self, sender: str, conversation: str, text: str, say: Say) -> None:
        known = self.sessions.get(conversation)
        session_id = known or str(uuid.uuid4())

        async def confirm(tool: str, arguments: Mapping[str, Any]) -> bool:
            answer: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self._pending[conversation] = _Pending(sender, answer)
            try:
                await say(write_request(tool, arguments))
                return await asyncio.wait_for(answer, self.confirm_timeout)
            except asyncio.TimeoutError:
                await say(NO_ANSWER)
                return False
            finally:
                self._pending.pop(conversation, None)

        try:
            async for chunk in self.agent.run(session_id, known is not None, text, confirm):
                if chunk.strip():
                    await say(chunk)
        except Exception:  # the conversation must hear that the turn died, whatever killed it
            log.exception("a turn failed in conversation %s", conversation)
            await say(FAILED)
            return
        if known is None:
            self.sessions.set(conversation, session_id)  # only a session that ran a whole turn is resumed
