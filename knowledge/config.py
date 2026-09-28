"""The publisher's config: where a docs tree goes in Confluence (design:
agentic_optimization_research roadmap/14 D26).

One TOML file per target, with the same rule as the board config: **no secrets
in the file.** `token_env` and `user_env` name the environment variables (or,
through `<NAME>_BW_ITEM`, the Bitwarden item) holding the classic Atlassian
API token and the account email, the pair the Jira adapter already uses
(D29). Only the keys below are accepted, so a pasted `token = …` never loads.

  [connection]  token_env, user_env, site
  [space]       key, parent       the page the tree's root page goes under
  [publish]     label, max_writes the shared label; page writes per run
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")  # Confluence labels hold no spaces; kept lowercase
_KEYS = {
    "connection": ({"token_env", "user_env", "site"}, set()),
    "space": ({"key", "parent"}, set()),
    "publish": (set(), {"label", "max_writes"}),
}  # section -> (required keys, optional keys)


class InvalidKnowledgeConfig(ValueError):
    """Raised by `load()` / `from_dict()`; `.problems` lists every violation."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class KnowledgeConfig:
    token_env: str
    user_env: str
    site: str
    space: str  # the space key
    parent: str  # the page id the tree's root page goes under
    label: str = "md-published"  # every page the publisher made carries it
    max_writes: int = 50  # page creates + updates per run


def from_dict(data: Mapping[str, Any]) -> KnowledgeConfig:
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
    conn, space, pub = tables["connection"], tables["space"], tables["publish"]
    for key in ("token_env", "user_env"):
        if key in conn and not (isinstance(conn[key], str) and _ENV_NAME.match(conn[key])):
            problems.append(f"connection.{key} must be the *name* of an environment variable, not a value")
    for where, value in (("connection.site", conn.get("site")), ("space.key", space.get("key"))):
        if value is not None and not (isinstance(value, str) and value.strip()):
            problems.append(f"{where} must be a non-empty string")
    parent = space.get("parent")
    if parent is not None and not (isinstance(parent, (str, int)) and str(parent).isdigit()):
        problems.append("space.parent must be a page id (digits)")
    label = pub.get("label", KnowledgeConfig.label)
    if not (isinstance(label, str) and _LABEL.match(label)):
        problems.append("publish.label must be lowercase letters, digits, - or _ (no spaces)")
    max_writes = pub.get("max_writes", KnowledgeConfig.max_writes)
    if isinstance(max_writes, bool) or not isinstance(max_writes, int) or max_writes < 1:
        problems.append("publish.max_writes must be a whole number of at least 1")
    if problems:
        raise InvalidKnowledgeConfig(problems)
    return KnowledgeConfig(conn["token_env"], conn["user_env"], conn["site"].strip(), space["key"].strip(),
                           str(parent), label, max_writes)


def load(path: str | Path) -> KnowledgeConfig:
    """Read a TOML publisher config and check it."""
    with open(path, "rb") as fh:
        return from_dict(tomllib.load(fh))
