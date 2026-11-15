"""What a planner reads from a code host, whichever host it is.

An `IssueSource` answers one question: which issues are open. A host is one
class with that method; `issues.github` is the first. Nothing here writes,
and no source may.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    url: str  # the page a person opens
    labels: tuple[str, ...] = ()
    updated: str = ""  # YYYY-MM-DD
    body: str = ""


class IssueSource(Protocol):
    def open_issues(self, limit: int) -> list[Issue]:
        """Up to `limit` open issues, most recently updated first. Pull
        requests are not issues and are left out."""
        ...
