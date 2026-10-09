"""Run the MCP server over stdio for one board or several (D43):

  uv run python -m server boards/<board>.toml
  uv run python -m server boards/

A directory serves each `*.toml` in it that has a `backend`, named by its
file stem; any other TOML there, such as a docs config, is skipped and named
on stderr. No board is read at start. The first tool call reads it, so a
missing token or a locked Bitwarden vault shows up as a tool error the agent
can report, not as a server that fails to start. Nothing but the protocol
may go to stdout; errors before the server starts go to stderr.
"""

from __future__ import annotations

import argparse
import sys

from adapters.base import Adapter
from adapters.jira import JiraAdapter
from adapters.plane import PlaneAdapter
from server.config import Backend, BoardConfig, InvalidBoardConfig, load_boards
from server.mcp_app import build
from server.service import Boards, BoardService


def make_adapter(cfg: BoardConfig) -> Adapter:
    if cfg.backend is Backend.PLANE:
        return PlaneAdapter(cfg)
    if cfg.backend is Backend.JIRA:
        return JiraAdapter(cfg)
    raise SystemExit(f"no adapter for backend {cfg.backend.value!r} yet (Plane and Jira only)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server", description="the agentic_administration MCP server (stdio)")
    parser.add_argument("config", nargs="+", help="a board's TOML config, or a directory of them")
    args = parser.parse_args(argv)
    try:
        configs, skipped = load_boards(args.config)
    except OSError as exc:
        print(f"cannot read the board config: {exc}", file=sys.stderr)
        return 2
    except InvalidBoardConfig as exc:
        print("invalid board config:\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    for path in skipped:
        print(f"skipped {path}: it has no backend, so it is not a board config", file=sys.stderr)
    build(Boards([BoardService(make_adapter(cfg), name=name) for name, cfg in configs.items()])).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
