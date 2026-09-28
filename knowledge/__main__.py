"""Operator entry: publish a Markdown tree to Confluence (roadmap/14 Phase 6b).

  uv run python -m knowledge publish <dir> --config <confluence.toml>            # dry run: read, plan
  uv run python -m knowledge publish <dir> --config <confluence.toml> --apply    # write

The token and the account email come from the secrets boundary (`token_env` /
`user_env`, or `<name>_BW_ITEM` + `BW_SESSION`), the same classic token as the
Jira adapter (D29); nothing secret is printed. Prints what was (or would be)
done, leaving out unchanged pages; exits 1 when a page was skipped or hit a
conflict, or the run stopped on an error, and 2 on a bad config.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from adapters.jira.transport import JiraTransport
from knowledge.config import InvalidKnowledgeConfig, load
from knowledge.confluence import Confluence
from knowledge.publish import Report, publish
from server import secrets

_ORDER = ("create", "update", "unchanged", "deferred", "orphan", "drift", "skip", "conflict", "warn")


def summary(report: Report) -> str:
    lines = [] if report.applied else ["dry run: nothing written (--apply writes it)"]
    for e in report.entries:
        if e.action != "unchanged":
            title = f' "{e.title}"' if e.title else ""
            lines.append(f"{e.action:<9}  {e.key}{title}" + (f"  — {e.note}" if e.note else ""))
    counts = report.counts()
    tally = ", ".join(f"{counts[a]} {a}" for a in _ORDER if counts[a])
    lines.append(f"{tally or 'nothing to publish'}; {report.writes} page write(s)"
                 + ("" if report.applied else " planned"))
    if report.error:
        lines.append(f"stopped: {report.error}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m knowledge")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("publish", help="publish a Markdown tree to Confluence (a dry run unless --apply)")
    p.add_argument("dir", help="the tree's root folder")
    p.add_argument("--config", required=True, help="the publisher's TOML config")
    p.add_argument("--apply", action="store_true", help="write; without it, read and plan only")
    p.add_argument("--max-writes", type=int, help="page creates + updates this run (overrides publish.max_writes)")
    args = parser.parse_args(argv)
    if args.max_writes is not None and args.max_writes < 1:
        parser.error("--max-writes must be at least 1")

    try:
        cfg = load(args.config)
    except InvalidKnowledgeConfig as exc:
        print("invalid publisher config:\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    root = Path(args.dir)
    if not root.is_dir():
        print(f"error: {root} is not a folder", file=sys.stderr)
        return 2
    transport = JiraTransport(cfg.site, lambda: secrets.get(cfg.user_env), lambda: secrets.get(cfg.token_env))
    report = publish(root, cfg, Confluence(transport), apply=args.apply, max_writes=args.max_writes)
    print(summary(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
