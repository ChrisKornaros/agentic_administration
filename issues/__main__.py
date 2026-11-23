"""Run the open-issues MCP server over stdio:

  uv run python -m issues serve --config <issues.toml>

The token comes from the secrets boundary (`token_env`, or `<name>_BW_ITEM` +
`BW_SESSION`); nothing secret is printed. The code host is first read on the
first tool call, so a token problem is a tool error. An empty `--config`
serves no tools, so a host can start the server whether or not the team has
one configured. Nothing but the protocol goes to stdout.
"""

from __future__ import annotations

import argparse
import sys

from issues.azure_devops import AzureDevOpsPullRequests
from issues.config import InvalidIssuesConfig, IssuesConfig, load
from issues.github import GitHubIssues
from issues.reader import OpenIssues
from issues.source import IssueSource
from server import secrets


def make_source(cfg: IssuesConfig) -> IssueSource:
    if cfg.kind == "github":
        return GitHubIssues(cfg.api, cfg.repository, lambda: secrets.get(cfg.token_env))
    if cfg.kind == "azure_devops":
        return AzureDevOpsPullRequests(cfg.api, cfg.organization or "", cfg.repository,
                                       lambda: secrets.get(cfg.token_env), auth=cfg.auth or "pat")
    raise SystemExit(f"no issue source for kind {cfg.kind!r} yet")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m issues")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="serve find_open_issues over stdio (the issues MCP server)")
    s.add_argument("--config", required=True, help="the open-issues TOML config; empty serves no tools")
    args = parser.parse_args(argv)
    if not args.config.strip():
        return serve(None)
    try:
        cfg = load(args.config)
    except OSError as exc:
        print(f"cannot read the open-issues config: {exc}", file=sys.stderr)
        return 2
    except InvalidIssuesConfig as exc:
        print("invalid open-issues config:\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    return serve(OpenIssues(cfg, make_source(cfg)))


def serve(reader: OpenIssues | None) -> int:
    from issues.mcp_app import build

    build(reader).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
