"""Run the MCP server over stdio for one board:

  uv run python -m server boards/<board>.toml

The board is not read at start. The first tool call reads it, so a
missing token or a locked Bitwarden vault shows up as a tool error the
agent can report, not as a server that fails to start. Nothing but the
protocol may go to stdout; errors before the server starts go to stderr.
"""

from __future__ import annotations

import argparse
import sys

from adapters.base import Adapter
from adapters.jira import JiraAdapter
from adapters.plane import PlaneAdapter
from server.config import Backend, BoardConfig, InvalidBoardConfig, load
from server.mcp_app import build
from server.service import BoardService


def make_adapter(cfg: BoardConfig) -> Adapter:
    if cfg.backend is Backend.PLANE:
        return PlaneAdapter(cfg)
    if cfg.backend is Backend.JIRA:
        return JiraAdapter(cfg)
    raise SystemExit(f"no adapter for backend {cfg.backend.value!r} yet (Plane and Jira only)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server", description="the agentic_administration MCP server (stdio)")
    parser.add_argument("config", help="path to the board's TOML config")
    args = parser.parse_args(argv)
    try:
        cfg = load(args.config)
    except OSError as exc:
        print(f"cannot read the board config: {exc}", file=sys.stderr)
        return 2
    except InvalidBoardConfig as exc:
        print("invalid board config:\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    build(BoardService(make_adapter(cfg))).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
