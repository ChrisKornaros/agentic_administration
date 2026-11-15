"""The open-issues config: which repository's issues a planner may read.

One TOML file per repository, with the board config's rule: **no secrets in
the file.** `token_env` names the environment variable (or, through
`<NAME>_BW_ITEM`, the Bitwarden item) that holds a token with read access to
that repository's issues. Only the keys below are accepted, so a pasted
`token = …` never loads.

  [connection]  token_env
  [source]      kind, repository, api   kind is "github"; api is its REST root
  [match]       key_pattern             finds a board key in an issue's text

`key_pattern` is a regular expression with one group, the key. It is tried on
every line of an issue's body, so `^Board: (\\S+)$` reads a footer line. With
no pattern, no issue names a key.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
KINDS = ("github",)
GITHUB_API = "https://api.github.com"
_KEYS = {
    "connection": ({"token_env"}, set()),
    "source": ({"kind", "repository"}, {"api"}),
    "match": (set(), {"key_pattern"}),
}  # section -> (required keys, optional keys)


class InvalidIssuesConfig(ValueError):
    """Raised by `load()` / `from_dict()`; `.problems` lists every violation."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class IssuesConfig:
    token_env: str
    kind: str
    repository: str  # owner/name
    api: str = GITHUB_API
    key_pattern: str | None = None


def from_dict(data: Mapping[str, Any]) -> IssuesConfig:
    problems = [f"unknown top-level keys: {', '.join(sorted(set(data) - set(_KEYS)))}"] if set(data) - set(_KEYS) else []
    tables: dict[str, dict[str, Any]] = {}
    for section, (required, optional) in _KEYS.items():
        table = data.get(section, {})
        if not isinstance(table, Mapping):
            problems.append(f"{section} must be a table")
            table = {}
        tables[section] = dict(table)
        if extra := sorted(set(table) - required - optional):
            problems.append(f"{section}: unknown keys {', '.join(extra)} (secrets never go in this file)")
        if missing := sorted(required - set(table)):
            problems.append(f"{section} needs: {', '.join(missing)}")
    conn, source, match = tables["connection"], tables["source"], tables["match"]
    token_env = conn.get("token_env")
    if token_env is not None and not (isinstance(token_env, str) and _ENV_NAME.match(token_env)):
        problems.append("connection.token_env must be the *name* of an environment variable, not a value")
    kind = source.get("kind")
    if kind is not None and kind not in KINDS:
        problems.append(f"source.kind must be one of: {', '.join(KINDS)}")
    repository = source.get("repository")
    if repository is not None and not (isinstance(repository, str) and _REPOSITORY.match(repository)):
        problems.append("source.repository must be owner/name")
    api = source.get("api", GITHUB_API)
    if not (isinstance(api, str) and api.startswith("https://")):
        problems.append("source.api must be an https:// URL")
    pattern = match.get("key_pattern")
    if pattern is not None:
        try:
            if not isinstance(pattern, str) or re.compile(pattern).groups != 1:
                problems.append("match.key_pattern must be a regular expression with exactly one group, the key")
        except re.error as exc:
            problems.append(f"match.key_pattern is not a regular expression: {exc}")
    if problems:
        raise InvalidIssuesConfig(problems)
    return IssuesConfig(token_env, kind, repository, api.rstrip("/"), pattern)


def load(path: str | Path) -> IssuesConfig:
    """Read a TOML open-issues config and check it."""
    with open(path, "rb") as fh:
        return from_dict(tomllib.load(fh))
