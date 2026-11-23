"""The open-issues config: which repository's issues a planner may read.

One TOML file per repository, with the board config's rule: **no secrets in
the file.** `token_env` names the environment variable (or, through
`<NAME>_BW_ITEM`, the Bitwarden item) that holds a token with read access to
that repository's issues. Only the keys below are accepted, so a pasted
`token = …` never loads.

  [connection]  token_env, auth
  [source]      kind, repository, api, organization
  [match]       key_pattern             finds a board key in an issue's text

`kind` is `github` or `azure_devops`, and `api` is the host's REST root,
which each kind has a default for.

- **github:** `repository` is `owner/name`. No `organization`, no `auth`.
- **azure_devops:** `organization` is the organization's name and
  `repository` is `Project/repository`, or `Project/*` for every repository
  in the project. Azure Repos has no issues of its own, so the open items
  are its active pull requests. `auth` says what the token is: `pat` (the
  default, a personal access token) or `bearer` (a Microsoft Entra token).

`key_pattern` is a regular expression with one group, the key. It is tried on
every line of an issue's body, so `^Board: (\\S+)$` reads a footer line. For a
pull request the lines are its title, then its source branch, then its
description. With no pattern, no issue names a key.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
_ORGANIZATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
_PROJECT_REPOSITORY = re.compile(r"^[^/\s][^/]*/(\*|[^/\s*][^/]*)$")  # a project's name may hold spaces
KINDS = ("github", "azure_devops")
AUTHS = ("pat", "bearer")
GITHUB_API = "https://api.github.com"
AZURE_DEVOPS_API = "https://dev.azure.com"
_API = {"github": GITHUB_API, "azure_devops": AZURE_DEVOPS_API}
_KEYS = {
    "connection": ({"token_env"}, {"auth"}),
    "source": ({"kind", "repository"}, {"api", "organization"}),
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
    repository: str  # github: owner/name; azure_devops: Project/repository or Project/*
    api: str = GITHUB_API
    key_pattern: str | None = None
    organization: str | None = None  # azure_devops only
    auth: str | None = None  # azure_devops only: "pat" or "bearer"


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
    repository, organization, auth = source.get("repository"), source.get("organization"), conn.get("auth")
    if kind == "azure_devops":
        auth = "pat" if auth is None else auth
        if auth not in AUTHS:
            problems.append(f"connection.auth must be one of: {', '.join(AUTHS)}")
        if organization is None:
            problems.append("source needs: organization")
        elif not (isinstance(organization, str) and _ORGANIZATION.match(organization)):
            problems.append("source.organization must be the organization's name, not a URL")
        if repository is not None and not (isinstance(repository, str) and _PROJECT_REPOSITORY.match(repository)):
            problems.append("source.repository must be Project/repository, or Project/* for the whole project")
    else:
        for key, value in (("connection.auth", auth), ("source.organization", organization)):
            if value is not None:
                problems.append(f"{key} is for kind azure_devops only")
        if repository is not None and not (isinstance(repository, str) and _REPOSITORY.match(repository)):
            problems.append("source.repository must be owner/name")
    api = source.get("api", _API.get(kind, GITHUB_API))
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
    return IssuesConfig(token_env, kind, repository, api.rstrip("/"), pattern, organization, auth)


def load(path: str | Path) -> IssuesConfig:
    """Read a TOML open-issues config and check it."""
    with open(path, "rb") as fh:
        return from_dict(tomllib.load(fh))
