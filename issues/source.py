"""What a planner reads from a code host, whichever host it is.

An `IssueSource` answers one question: which issues are open. A host is one
class with that method: `issues.github`, and `issues.azure_devops`, whose
host has no issues of its own and answers with its open pull requests.
Nothing here writes, and no source may.
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
    body: str = ""  # the text a board key may be in, a line at a time; never returned to a planner


class IssueSource(Protocol):
    def open_issues(self, limit: int) -> list[Issue]:
        """Up to `limit` open issues, most recently updated first. Where a
        host has issues, pull requests are not issues and are left out."""
        ...
