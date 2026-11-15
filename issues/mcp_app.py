"""The `issues` MCP server: `find_open_issues` over `OpenIssues`, on the
official `mcp` SDK's `MCPServer`.

It is separate from the board server, which keeps its eleven tools, for the
reason the knowledge server is: a host loads this one only where a team's
code host is configured. The tool reads, and an `IssuesFailure` reaches the
client as an `is_error` result carrying its message.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from issues.reader import IssuesFailure, OpenIssues
from server import __version__

READ = ToolAnnotations(read_only_hint=True)

INSTRUCTIONS = """\
The open issues on the team's code host, read-only. find_open_issues lists
them, most recently updated first, each with the board keys its text names.
An issue that names no key may still be on the board under a link."""


def build(reader: OpenIssues | None) -> MCPServer:
    """The server; with no `reader` (a host with no code host configured), it has no tools."""
    mcp = MCPServer("agentic-administration-issues", instructions=INSTRUCTIONS if reader else None,
                    version=__version__)
    if reader is None:
        return mcp

    @mcp.tool(annotations=READ)
    def find_open_issues(limit: int = 50) -> dict[str, Any]:
        """The open issues on the team's code host, most recently updated
        first, up to `limit` (at most 200). Each has its number, title, URL,
        labels, the day it was last updated and `item_keys`: the board keys
        its text names, empty when it names none. Pull requests are not
        listed. If exactly `limit` come back, there may be more."""
        try:
            return {"issues": reader.find_open_issues(limit)}
        except IssuesFailure as exc:
            raise ToolError(str(exc)) from None

    return mcp
