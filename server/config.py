"""The board config — the "only settings" surface (design: agentic_optimization_research
roadmap/14 §6, decision D7).

One file per board. Pointing the tool at a supported tracker is *this* file
and nothing else: which backend, how to reach the board, how the canonical
levels map onto the tracker's types or containers, how the canonical states
map onto the workflow, the review label, naming rules, and the confirm mode.

**No secrets in the file.** The connection names the environment variable
that holds the API token (`token_env`); the adapter reads it at the boundary
(design: modules/secrets-no-plaintext). A value that does not look like an
env-var name, or a connection key that looks like it holds a credential, is
rejected at load time so a pasted token never validates.

The file format is TOML (`tomllib`, stdlib); `BoardConfig.from_dict` takes
the same shape from any source. Validation mirrors `WorkItem`: every problem
is collected and raised at once as `InvalidBoardConfig`.

Static checks only — nothing here talks to a tracker. The *live* check
(do the named types, states and labels exist on the board) is the adapter's
`describe_board` on start, which aborts before any write.
"""

from __future__ import annotations

import enum
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from server.model import (
    CORE_LEVELS,
    CollapseRule,
    CollapseTarget,
    Level,
    Materialization,
    State,
)


class Backend(enum.Enum):
    PLANE = "plane"
    JIRA = "jira"
    ADO = "ado"
    GENERIC = "generic"


class Confirm(enum.Enum):
    """D5: propose-then-confirm is the default write mode."""

    ALWAYS = "always"
    NEVER = "never"


class ItemCase(enum.Enum):
    """Title-case rule for work items; `ANY` means no rule is enforced."""

    TITLE = "title"  # Proper Case Like This (Chris's boards, CONVENTIONS §3)
    SENTENCE = "sentence"
    ANY = "any"


# Identifiers each backend needs beyond `token_env` / `base_url`. Jira needs
# both a project key and an Agile board id because sprints belong to a board.
CONNECTION_KEYS: Mapping[Backend, frozenset[str]] = {
    Backend.PLANE: frozenset({"workspace", "project"}),
    Backend.JIRA: frozenset({"site", "project_key", "board_id"}),
    Backend.ADO: frozenset({"organization", "project"}),
    Backend.GENERIC: frozenset(),
}

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Connection keys that would only ever hold a credential.
_SECRET_KEY_WORDS = ("token", "api_key", "apikey", "password", "secret")
# The one-key-per-level forms `[levels]` accepts, and what each materializes as.
_LEVEL_FORMS: Mapping[str, Materialization] = {
    "type": Materialization.TYPE,
    "container": Materialization.CONTAINER,
    "parent": Materialization.PARENT,
    "label": Materialization.LABEL,
    "collapse": Materialization.NONE,
}


class InvalidBoardConfig(ValueError):
    """Raised by `BoardConfig.check()` / `load()`; `.problems` lists every violation."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


# --- sections --------------------------------------------------------------


@dataclass(frozen=True)
class Connection:
    """How to reach the board. `token_env` is the *name* of the env var
    holding the API token; `ids` are the backend-specific identifiers
    (`CONNECTION_KEYS`); `base_url` is optional and defaults per adapter."""

    token_env: str
    ids: Mapping[str, str] = field(default_factory=dict)
    base_url: str | None = None


@dataclass(frozen=True)
class LevelMapping:
    """One canonical level's realization on the board.

    `ref` is the native type (id or name) for `TYPE`, the container kind
    (e.g. `module`) for `CONTAINER`, the label carried next to the parent
    link for `PARENT`, or the label itself for `LABEL`. `NONE` carries a
    `collapse` rule instead.
    """

    how: Materialization
    ref: str | None = None
    collapse: CollapseRule | None = None


@dataclass(frozen=True)
class Labels:
    review: str  # D5: the marker a fresh item carries until the PO clears it
    taxonomy: tuple[str, ...] = ()  # the per-board label set (CONVENTIONS §4)


@dataclass(frozen=True)
class Naming:
    iteration: str = "YYYYMM"  # pattern with YYYY / MM / DD tokens
    item_case: ItemCase = ItemCase.ANY

    def iteration_regex(self) -> re.Pattern[str]:
        pattern = re.escape(self.iteration)
        for token, sub in (("YYYY", r"\d{4}"), ("MM", r"\d{2}"), ("DD", r"\d{2}")):
            pattern = pattern.replace(token, sub)
        return re.compile(f"^{pattern}$")

    def iteration_name_ok(self, name: str) -> bool:
        return self.iteration_regex().match(name) is not None


# --- the config ------------------------------------------------------------


@dataclass(frozen=True)
class BoardConfig:
    backend: Backend
    connection: Connection
    levels: Mapping[Level, LevelMapping]
    states: Mapping[State, str]
    labels: Labels
    naming: Naming = field(default_factory=Naming)
    confirm: Confirm = Confirm.ALWAYS

    # -- validation ---------------------------------------------------------

    def validate(self) -> list[str]:
        """Return every static violation; empty means valid."""
        problems: list[str] = []
        problems += self._validate_connection()
        problems += self._validate_levels()
        problems += self._validate_states()
        if not self.labels.review.strip():
            problems.append("labels.review is empty (the review marker is required)")
        return problems

    def _validate_connection(self) -> list[str]:
        problems: list[str] = []
        conn = self.connection
        if not _ENV_NAME.match(conn.token_env):
            problems.append(
                "connection.token_env must be the *name* of an environment variable, "
                "not a value"
            )
        for key in conn.ids:
            if any(word in key.lower() for word in _SECRET_KEY_WORDS):
                problems.append(
                    f"connection.{key} looks like a credential — secrets never go in "
                    "the board config; name the env var in token_env instead"
                )
        missing = sorted(CONNECTION_KEYS[self.backend] - set(conn.ids))
        if missing:
            problems.append(
                f"connection for {self.backend.value} needs: {', '.join(missing)}"
            )
        empty = sorted(k for k, v in conn.ids.items() if not str(v).strip())
        if empty:
            problems.append(f"connection values are empty: {', '.join(empty)}")
        return problems

    def _validate_levels(self) -> list[str]:
        problems: list[str] = []
        missing = sorted(lv.value for lv in Level if lv not in self.levels)
        if missing:
            problems.append(f"levels missing: {', '.join(missing)}")
        for level, mapping in self.levels.items():
            if mapping.how is Materialization.NONE:
                if level in CORE_LEVELS:
                    problems.append(
                        f"levels.{level.value} is a core level and cannot collapse"
                    )
                if mapping.collapse is None:
                    problems.append(f"levels.{level.value} collapses without a rule")
            else:
                if not (mapping.ref or "").strip():
                    problems.append(
                        f"levels.{level.value} ({mapping.how.value}) needs a non-empty target"
                    )
                if mapping.collapse is not None:
                    problems.append(
                        f"levels.{level.value} is materialized and cannot also collapse"
                    )
        return problems

    def _validate_states(self) -> list[str]:
        problems: list[str] = []
        missing = sorted(st.value for st in State if st not in self.states)
        if missing:
            problems.append(f"states missing: {', '.join(missing)}")
        empty = sorted(st.value for st, name in self.states.items() if not name.strip())
        if empty:
            problems.append(f"states mapped to an empty name: {', '.join(empty)}")
        return problems

    def check(self) -> BoardConfig:
        problems = self.validate()
        if problems:
            raise InvalidBoardConfig(problems)
        return self

    # -- derived views ------------------------------------------------------

    def materializations(self) -> dict[Level, Materialization]:
        """The `Capabilities.levels` shape this config implies."""
        return {lv: m.how for lv, m in self.levels.items()}

    def collapse_rules(self) -> dict[Level, CollapseRule]:
        """The `Capabilities.collapse` shape this config implies."""
        return {lv: m.collapse for lv, m in self.levels.items() if m.collapse is not None}

    # -- construction -------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BoardConfig:
        """Build from the TOML shape. Shape errors (wrong types, unknown keys,
        bad enum values) raise `InvalidBoardConfig` here; rule violations are
        left to `validate()` / `check()` so a caller can list both at once."""
        problems: list[str] = []
        known = {"backend", "connection", "levels", "states", "labels", "naming", "confirm"}
        unknown = sorted(set(data) - known)
        if unknown:
            problems.append(f"unknown top-level keys: {', '.join(unknown)}")
        for key in ("backend", "connection", "levels", "states", "labels"):
            if key not in data:
                problems.append(f"missing section: {key}")
        if problems:
            raise InvalidBoardConfig(problems)

        backend = _enum(Backend, data["backend"], "backend", problems)
        connection = _connection(data["connection"], problems)
        levels = _levels(data["levels"], problems)
        states = _states(data["states"], problems)
        labels = _labels(data["labels"], problems)
        naming = _naming(data.get("naming", {}), problems)
        confirm = _enum(Confirm, data.get("confirm", "always"), "confirm", problems)
        if problems:
            raise InvalidBoardConfig(problems)
        return cls(
            backend=backend,
            connection=connection,
            levels=levels,
            states=states,
            labels=labels,
            naming=naming,
            confirm=confirm,
        )


def load(path: str | Path) -> BoardConfig:
    """Read a TOML board config, build it, and `check()` it."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return BoardConfig.from_dict(data).check()


# --- section parsers (each appends to `problems`, never raises) --------------


def _enum(kind: type[enum.Enum], value: Any, where: str, problems: list[str]) -> Any:
    try:
        return kind(value)
    except ValueError:
        allowed = ", ".join(m.value for m in kind)
        problems.append(f"{where}: {value!r} is not one of {allowed}")
        return next(iter(kind))


def _table(value: Any, where: str, problems: list[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        problems.append(f"{where} must be a table")
        return {}
    return dict(value)


def _connection(raw: Any, problems: list[str]) -> Connection:
    table = _table(raw, "connection", problems)
    token_env = table.pop("token_env", None)
    if not isinstance(token_env, str):
        problems.append("connection.token_env is required (the env var name)")
        token_env = ""
    base_url = table.pop("base_url", None)
    if base_url is not None and not isinstance(base_url, str):
        problems.append("connection.base_url must be a string")
        base_url = None
    ids: dict[str, str] = {}
    for key, value in table.items():
        if not isinstance(value, (str, int)):
            problems.append(f"connection.{key} must be a string")
            continue
        ids[key] = str(value)
    return Connection(token_env=token_env, ids=ids, base_url=base_url)


def _levels(raw: Any, problems: list[str]) -> dict[Level, LevelMapping]:
    table = _table(raw, "levels", problems)
    out: dict[Level, LevelMapping] = {}
    for key, spec in table.items():
        try:
            level = Level(key)
        except ValueError:
            problems.append(f"levels.{key}: unknown level")
            continue
        spec = _table(spec, f"levels.{key}", problems)
        forms = [k for k in spec if k in _LEVEL_FORMS]
        extra = sorted(k for k in spec if k not in _LEVEL_FORMS and k != "template")
        if extra:
            problems.append(f"levels.{key}: unknown keys {', '.join(extra)}")
        if len(forms) != 1:
            problems.append(
                f"levels.{key}: give exactly one of {', '.join(_LEVEL_FORMS)}"
            )
            continue
        form = forms[0]
        how = _LEVEL_FORMS[form]
        if how is Materialization.NONE:
            target = _enum(CollapseTarget, spec[form], f"levels.{key}.collapse", problems)
            template = spec.get("template", CollapseRule.template)
            if not isinstance(template, str):
                problems.append(f"levels.{key}.template must be a string")
                template = CollapseRule.template
            out[level] = LevelMapping(how, collapse=CollapseRule(target, template))
        else:
            if "template" in spec:
                problems.append(f"levels.{key}: template only applies to collapse")
            ref = spec[form]
            if not isinstance(ref, str):
                problems.append(f"levels.{key}.{form} must be a string")
                ref = ""
            out[level] = LevelMapping(how, ref=ref)
    return out


def _states(raw: Any, problems: list[str]) -> dict[State, str]:
    table = _table(raw, "states", problems)
    out: dict[State, str] = {}
    for key, name in table.items():
        try:
            state = State(key)
        except ValueError:
            problems.append(f"states.{key}: unknown canonical state")
            continue
        if not isinstance(name, str):
            problems.append(f"states.{key} must be a string")
            continue
        out[state] = name
    return out


def _labels(raw: Any, problems: list[str]) -> Labels:
    table = _table(raw, "labels", problems)
    review = table.get("review")
    if not isinstance(review, str):
        problems.append("labels.review is required (the review marker, e.g. needs-review)")
        review = ""
    taxonomy = table.get("taxonomy", [])
    if not isinstance(taxonomy, list) or not all(isinstance(t, str) for t in taxonomy):
        problems.append("labels.taxonomy must be a list of strings")
        taxonomy = []
    unknown = sorted(set(table) - {"review", "taxonomy"})
    if unknown:
        problems.append(f"labels: unknown keys {', '.join(unknown)}")
    return Labels(review=review, taxonomy=tuple(taxonomy))


def _naming(raw: Any, problems: list[str]) -> Naming:
    table = _table(raw, "naming", problems)
    unknown = sorted(set(table) - {"iteration", "item_case"})
    if unknown:
        problems.append(f"naming: unknown keys {', '.join(unknown)}")
    iteration = table.get("iteration", Naming.iteration)
    if not isinstance(iteration, str) or not iteration.strip():
        problems.append("naming.iteration must be a non-empty pattern")
        iteration = Naming.iteration
    item_case = _enum(ItemCase, table.get("item_case", "any"), "naming.item_case", problems)
    return Naming(iteration=iteration, item_case=item_case)
