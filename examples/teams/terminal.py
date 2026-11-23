"""The bridge with no Teams: type to the backlog agent through `Bridge`, or
pipe a scripted conversation into it.

It is the check that the bridge, the Agent SDK and this repo's plugin work
together before a chat platform is involved: every line is one message
from the owner in one conversation, a write's yes or no is the next line,
and `/new` starts over. The sessions file and the agent's working
directory go under `--state`, so a second run resumes the first.

    export AGENTIC_ADMIN_BOARD=boards/<board>.toml   # or boards/; plus each board's token env
    uv run --group agent-sdk python examples/teams/terminal.py
    uv run --group agent-sdk python examples/teams/terminal.py < a-conversation.txt

It prints which billing the turns run on first. With no metered credential
in the environment that is the Claude plan login of whoever runs it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent import ClaudeAgent  # noqa: E402
from bridge import Bridge, Sessions, billing  # noqa: E402

OWNER, CONVERSATION = "terminal", "terminal"


async def say(text: str) -> None:
    print(f"\n{text}", flush=True)


async def read_line(prompt: str) -> str | None:
    if sys.stdin.isatty():
        print(prompt, end="", flush=True)
    line = await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
    return line if line else None  # None at end of input


async def chat(bridge: Bridge) -> None:
    turns: set[asyncio.Task[None]] = set()
    while (line := await read_line("\n> ")) is not None:
        if not line.strip():
            continue
        task = asyncio.create_task(bridge.handle(OWNER, CONVERSATION, line, say))
        turns.add(task)
        task.add_done_callback(turns.discard)
        await asyncio.sleep(0)
        # the next line is wanted when the turn is over, or when a write waits for its answer
        while not task.done() and not bridge.waiting(CONVERSATION):
            await asyncio.sleep(0.1)
    if turns:
        await asyncio.gather(*turns)  # a piped conversation ends with its last turn, not mid-turn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="terminal.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", default=str(Path.home() / ".cache" / "agentic-administration" / "bridge"),
                        help="where the sessions file and the agent's working directory go")
    parser.add_argument("--model", help="the model, or a deployment's name (default: AGENTIC_ADMIN_MODEL, then the example's)")
    args = parser.parse_args(argv)
    state = Path(args.state)
    bridge = Bridge(ClaudeAgent(state / "cwd", model=args.model), Sessions(state / "sessions.json"), owner=OWNER)
    print(f"billing: {bridge.mode}" + (" (the Claude plan login of whoever runs this)" if bridge.mode == "plan" else ""),
          file=sys.stderr)
    try:
        asyncio.run(chat(bridge))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
