"""The read side of the published docs: `search_docs` and `get_doc` (design:
agentic_optimization_research roadmap/14 D27).

The `knowledge` MCP server's two tools are thin wrappers over `Docs`, which
reads Confluence through the publisher's own client and config. The scope is
the pages the publisher made: those in `space.key` carrying `publish.label`.
A search is CQL `siteSearch` inside that scope. `get_doc` reads one page and
refuses a page outside it, so an id from a link cannot reach the rest of the
site. The body comes back as Markdown (`adf.to_markdown`), and a link to
another published page is that page's URL, which `get_doc` takes too.

The interface follows roadmap/07's `search_docs`: a query, `k`, and ranked
hits with an excerpt, then a second call for the whole text.

Every error the agent can act on becomes a `DocsFailure` whose message says
what to do. The SDK runs sync tools in threads and the transport's throttle
isn't thread-safe, so each call holds one lock. Nothing here writes.
"""

from __future__ import annotations

import functools
import html
import re
import threading
from typing import Any

from adapters.base import AdapterError, AuthError, NotFound, RateLimited
from adapters.jira import adf
from knowledge.config import KnowledgeConfig
from knowledge.confluence import Confluence, Space, page_version

MAX_K = 20
_HIGHLIGHT = re.compile(r"@@@(?:end)?hl@@@")
_PAGE_REF = re.compile(r"^(\d+)$|/pages/(\d+)(?:[/?#]|$)")


class DocsFailure(Exception):
    """A failure the calling agent can act on; the message says what to do."""


def _explain(exc: AdapterError) -> str:
    if isinstance(exc, AuthError):
        return f"Confluence refused the credentials ({exc}). The operator must fix the token; retrying will not help."
    if isinstance(exc, RateLimited):
        return f"Confluence is rate-limiting ({exc}). Wait about a minute, then retry the same call."
    if isinstance(exc, NotFound):
        return f"Not found: {exc}. If this was a page, use an id or URL that search_docs returned."
    return f"Confluence could not answer ({exc.__class__.__name__}: {exc}). Retry shortly."


def _operation(fn):
    """Serialize the call and turn adapter errors into `DocsFailure`."""

    @functools.wraps(fn)
    def wrapper(self: Docs, *args, **kwargs):
        with self._lock:
            try:
                return fn(self, *args, **kwargs)
            except AdapterError as exc:
                raise DocsFailure(_explain(exc)) from exc

    return wrapper


def _plain(text: Any) -> str:
    """A hit's excerpt as plain text: no highlight markers or entities, one line."""
    return " ".join(html.unescape(_HIGHLIGHT.sub("", str(text or ""))).split())


class Docs:
    def __init__(self, cfg: KnowledgeConfig, client: Confluence) -> None:
        self.cfg, self.client = cfg, client
        self._space: Space | None = None
        self._lock = threading.Lock()

    @property
    def space(self) -> Space:
        if self._space is None:
            self._space = self.client.space(self.cfg.space)
        return self._space

    @_operation
    def search_docs(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Up to `k` published pages matching `query`, best first."""
        if not query.strip():
            raise DocsFailure("The query is empty. Pass a few key words from the question.")
        hits = self.client.search(self.cfg.space, self.cfg.label, query.strip(), max(1, min(k, MAX_K)))
        out = []
        for hit in hits:
            page = hit.get("content") or {}
            if page.get("id"):
                pid = str(page["id"])
                out.append({"id": pid, "title": str(page.get("title") or _plain(hit.get("title"))),
                            "url": self.space.page_url(pid), "excerpt": _plain(hit.get("excerpt"))})
        return out

    @_operation
    def get_doc(self, ref: str) -> dict[str, Any]:
        """One published page by its id or URL, with its body as Markdown."""
        m = _PAGE_REF.search(ref.strip())
        if not m:
            raise DocsFailure(f"{ref!r} is not a page id or a page URL. Use an id or URL that search_docs returned.")
        pid = m.group(1) or m.group(2)
        page = self.client.page(pid)
        if str(page.get("spaceId")) != self.space.id or page.get("status", "current") != "current" \
                or self.cfg.label not in self.client.labels(pid):
            raise DocsFailure(f"Page {pid} is not one of the published docs, so it is not read here. "
                              "Use an id or URL that search_docs returned.")
        return {"id": pid, "title": str(page.get("title") or ""), "url": self.space.page_url(pid),
                "version": page_version(page), "markdown": adf.to_markdown(page.get("doc"))}
