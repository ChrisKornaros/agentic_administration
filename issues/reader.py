"""The read a planner makes: `find_open_issues`.

The `issues` MCP server's one tool is a thin wrapper over `OpenIssues`, which
asks an `IssueSource` for the open issues and adds, for each, the board keys
its text names (the config's `key_pattern`, tried on every line of the
body). An issue's body is not returned: a planner sorts issues, it does not
read them.

Every error the agent can act on becomes an `IssuesFailure` whose message
says what to do. The SDK runs sync tools in threads, so each call holds one
lock. Nothing here writes.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from adapters.base import AdapterError, AuthError, NotFound, RateLimited
from issues.config import IssuesConfig
from issues.source import IssueSource

MAX_LIMIT = 200


class IssuesFailure(Exception):
    """A failure the calling agent can act on; the message says what to do."""


def _explain(exc: AdapterError) -> str:
    if isinstance(exc, AuthError):
        return f"The code host refused the credentials ({exc}). The operator must fix the token; retrying will not help."
    if isinstance(exc, RateLimited):
        return f"The code host is rate-limiting ({exc}). Wait a few minutes, then retry the same call."
    if isinstance(exc, NotFound):
        return f"{exc}. The operator must fix the repository or the token's access; retrying will not help."
    return f"The code host could not answer ({exc.__class__.__name__}: {exc}). Retry shortly."


class OpenIssues:
    def __init__(self, cfg: IssuesConfig, source: IssueSource) -> None:
        self.cfg, self.source = cfg, source
        self._key = re.compile(cfg.key_pattern, re.MULTILINE) if cfg.key_pattern else None
        self._lock = threading.Lock()

    def keys(self, body: str) -> list[str]:
        """The board keys an issue's text names, in order, each once."""
        found = [m.group(1) for m in self._key.finditer(body)] if self._key else []
        return list(dict.fromkeys(k for k in found if k))

    def find_open_issues(self, limit: int = 50) -> list[dict[str, Any]]:
        """Up to `limit` open issues, most recently updated first."""
        with self._lock:
            try:
                issues = self.source.open_issues(max(1, min(limit, MAX_LIMIT)))
            except AdapterError as exc:
                raise IssuesFailure(_explain(exc)) from exc
        return [{"number": i.number, "title": i.title, "url": i.url, "labels": list(i.labels),
                 "updated": i.updated, "item_keys": self.keys(i.body)} for i in issues]
