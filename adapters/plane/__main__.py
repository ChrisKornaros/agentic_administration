"""Operator entry: read a board and check its config — never a write.

  uv run python -m adapters.plane describe boards/<board>.toml

Prints the board description as JSON (types, states, labels, members,
modules, cycles, per-level resolution) and the config-vs-board problems;
exits 1 when there are any. The token comes from the secrets boundary
(`token_env`, or `<token_env>_BW_ITEM` + `BW_SESSION`); nothing secret is
printed.
"""

from __future__ import annotations

import argparse
import json
import sys

from adapters.base import AdapterError
from adapters.plane.adapter import PlaneAdapter
from server.config import InvalidBoardConfig, load
from server.model import to_jsonable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m adapters.plane")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("describe", help="read the live board and check the config against it")
    p.add_argument("config", help="path to the board's TOML config")
    args = parser.parse_args(argv)

    try:
        cfg = load(args.config)
    except InvalidBoardConfig as exc:
        print("invalid board config:\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    try:
        board = PlaneAdapter(cfg).describe_board()
    except AdapterError as exc:
        print(f"error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        if exc.detail:
            print(f"  detail: {exc.detail}", file=sys.stderr)
        return 1
    print(json.dumps(to_jsonable(board), indent=2), flush=True)  # before the verdict, even when captured
    if board.problems:
        print("\nconfig does not fit the board:\n  - " + "\n  - ".join(board.problems), file=sys.stderr)
        return 1
    print("\nconfig fits the board.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
