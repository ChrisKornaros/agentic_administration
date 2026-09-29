"""The `knowledge` MCP server: `search_docs` and `get_doc` over `Docs` (design:
agentic_optimization_research roadmap/14 D27), on the official `mcp` SDK's
`MCPServer`.

It is separate from the board server, which keeps its eleven tools (D13): a
host loads this one only where a team publishes docs. Both tools read, and
a `DocsFailure` reaches the client as an `is_error` result carrying its
message.
"""

from __future__ import annotations

from typing import Any, Callable

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from knowledge.docs import Docs, DocsFailure

READ = ToolAnnotations(read_only_hint=True)

INSTRUCTIONS = """\
The team's published docs, read-only. search_docs finds pages by a few key
words and returns each page's title, URL and an excerpt; get_doc reads one
page in full, as Markdown. Read the page before you tell anyone what it says."""


def build(docs: Docs | None) -> MCPServer:
    """The server; with no `docs` (a host with no docs configured), it has no tools."""
    mcp = MCPServer("agentic-administration-knowledge", instructions=INSTRUCTIONS if docs else None)
    if docs is None:
        return mcp

    def call(fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return fn(*args)
        except DocsFailure as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool(annotations=READ)
    def search_docs(query: str, k: int = 5) -> dict[str, Any]:
        """Search the team's published docs. `query` is a few key words,
        not a sentence. Returns up to `k` pages (at most 20), best first,
        each with its id, title, URL and an excerpt around the match. An
        excerpt is a fragment: read the page with get_doc before relying on
        it."""
        return {"results": call(docs.search_docs, query, k)}

    @mcp.tool(annotations=READ)
    def get_doc(ref: str) -> dict[str, Any]:
        """One published page by the id or URL search_docs gave, or a page
        URL linked from another page: its title, URL, version and the whole
        body as Markdown."""
        return call(docs.get_doc, ref)

    return mcp
