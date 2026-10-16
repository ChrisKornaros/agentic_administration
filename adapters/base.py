"""The adapter interface — the domain operations the MCP server calls,
in canonical-model terms, plus the error taxonomy every backend maps its
vendor's failures onto (design: roadmap/14 §5 layer 2, applying
modules/external-api-adapter-boundary).

An adapter:

- takes a `BoardConfig` and declares its `Capabilities`;
- reads the live board once (`describe_board`) and checks the config
  against it — a missing type, state name or label is reported there and
  **every write refuses to run until the board description is clean**;
- speaks `WorkItem` / `Iteration` / `Comment` in and out, never raw vendor
  records;
- has **no delete** operation. Work is done or cancelled; nothing here can
  remove an item, an iteration or a comment.

Errors: callers `except AdapterError` (or a subclass) and never a vendor
exception. `ValidationError` covers the tracker rejecting a write —
including Plane's hierarchy rules, which have no read surface and only
show up as write errors (roadmap/14 §3.1).

Writing a new adapter: adapters/README.md.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

from server.config import BoardConfig
from server.model import (
    Capabilities,
    Comment,
    ItemRef,
    Iteration,
    Level,
    State,
    WorkItem,
)

# --- errors ------------------------------------------------------------------


class AdapterError(Exception):
    """Base of everything an adapter raises. `detail` is the vendor's own
    message (already stripped of anything secret) for the operator."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class AuthError(AdapterError):
    """The token was missing, invalid or lacks the permission."""


class NotFound(AdapterError):
    """The item / iteration / project the call named does not exist."""


class ValidationError(AdapterError):
    """The tracker rejected the write (shape, business rule, hierarchy)."""


class RateLimited(AdapterError):
    """The tracker asked us to slow down (HTTP 429); safe to retry later."""


class Blocked(AdapterError):
    """An edge wall in front of the tracker (Plane: the Cloudflare managed
    challenge / UA ban) answered instead of the API. Not a retry-now case."""


class TransportError(AdapterError):
    """Network failure, timeout, or a 5xx with no usable body."""


class Unsupported(AdapterError):
    """The backend cannot realize this operation for this level/field; the
    capabilities record says so and skills should not have asked."""


class ConfigMismatch(AdapterError):
    """The board config names something the live board lacks. `problems`
    lists every mismatch; raised before any write."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


# --- what describe_board returns --------------------------------------------


@dataclass(frozen=True)
class TypeInfo:
    id: str
    name: str
    is_epic: bool = False
    is_default: bool = False


@dataclass(frozen=True)
class StateInfo:
    id: str
    name: str
    group: str | None = None  # the tracker's own bucket, e.g. Plane `started`


@dataclass(frozen=True)
class NamedRef:
    """A label, member, container or iteration on the board: id + display name."""

    id: str
    name: str
    extra: Mapping[str, Any] = field(default_factory=dict)


class FieldKind(enum.Enum):
    """What a custom field holds, whatever the tracker calls it."""

    BOOLEAN = "boolean"
    OPTION = "option"  # one of `options`, or several when `multi`
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"  # an ISO date string
    OTHER = "other"  # written as given, unchecked


@dataclass(frozen=True)
class FieldInfo:
    """A config field (D41) as the live board carries it. `native` is the
    tracker's own type; `levels` maps each level whose type carries the field
    to the property or field id written there (Plane: one property per type)."""

    name: str
    kind: FieldKind
    native: str
    multi: bool = False
    options: tuple[str, ...] = ()
    levels: Mapping[Level, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BoardDescription:
    """The live board as the adapter read it, plus the config-vs-board check.

    `problems` is empty when the config fits the board. Ids in the other
    fields are the tracker's; `resolved` is the per-level native id the
    adapter will write (types for TYPE levels, the container kind for
    CONTAINER levels).
    """

    backend: str
    project_id: str
    project_key: str | None
    project_name: str | None
    features: Mapping[str, Any]
    types: tuple[TypeInfo, ...]
    states: tuple[StateInfo, ...]
    labels: tuple[NamedRef, ...]
    members: tuple[NamedRef, ...]
    containers: tuple[NamedRef, ...] = ()  # Plane modules
    iterations: tuple[NamedRef, ...] = ()  # Plane cycles
    resolved: Mapping[Level, str] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    fields: tuple[FieldInfo, ...] = ()  # the config's [fields], as found

    def check(self) -> BoardDescription:
        if self.problems:
            raise ConfigMismatch(list(self.problems))
        return self


def field_problems(board: BoardDescription, level: Level, values: Mapping[str, Any]) -> list[str]:
    """Every reason these custom-field values can't go on an item of `level`;
    empty means they can. An option field takes option names, a multi one a
    list of them; names match ignoring case."""
    known = {f.name: f for f in board.fields}
    problems: list[str] = []
    for name, value in values.items():
        info = known.get(name)
        if info is None:
            problems.append(f"no field {name!r} on this board (fields: {', '.join(known) or '(none)'})")
            continue
        if level not in info.levels:
            where = ", ".join(lv.value for lv in info.levels) or "no level"
            problems.append(f"field {name!r} is not on the {level.value} type (it is on: {where})")
            continue
        if info.kind is FieldKind.OPTION:
            names = value if isinstance(value, list) and info.multi else [value]
            wanted = {o.lower() for o in info.options}
            bad = [n for n in names if not isinstance(n, str) or (wanted and n.lower() not in wanted)]
            if bad or not names:
                shape = "a list of option names" if info.multi else "one option name"
                problems.append(f"field {name!r} takes {shape} (options: {', '.join(info.options) or '(unknown)'}); "
                                f"got {value!r}")
        elif not _kind_ok(info.kind, value):
            problems.append(f"field {name!r} takes a {info.kind.value} value; got {value!r}")
    return problems


def _kind_ok(kind: FieldKind, value: Any) -> bool:
    if kind is FieldKind.BOOLEAN:
        return isinstance(value, bool)
    if kind is FieldKind.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind is FieldKind.TEXT:
        return isinstance(value, str)
    if kind is FieldKind.DATE:
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            return False
    return True


def option_names(info: FieldInfo, value: Any) -> list[str]:
    """An option value as the board's own option names, for the wire."""
    by_lower = {o.lower(): o for o in info.options}
    names = value if isinstance(value, list) else [value]
    return [by_lower.get(n.lower(), n) for n in names]


def existing_iteration(found: Iteration, wanted: Iteration) -> Iteration:
    """Find-or-create's reuse check: the board's `found` stands in for
    `wanted` unless `wanted` gives a date that differs."""
    if (wanted.start and wanted.start != found.start) or (wanted.end and wanted.end != found.end):
        raise ValidationError(
            f"iteration {found.name!r} already exists, dated {found.start}–{found.end}; "
            "leave the dates out to use it as it is"
        )
    return found


# --- the changes an update may carry -----------------------------------------


@dataclass(frozen=True)
class ItemPatch:
    """Fields `update_item` may change; `None` means "leave as is". Sequences
    replace (labels=() clears every label — how the PO drops the review
    marker). `fields` sets the custom fields it names and leaves the others;
    a value can't be cleared here. Moving between iterations is
    `move_to_iteration`, not a patch; there is no way to change an item's
    level."""

    title: str | None = None
    description: str | None = None  # Markdown
    state: State | None = None
    assignees: Sequence[str] | None = None
    labels: Sequence[str] | None = None
    parent: ItemRef | None = None
    feature: ItemRef | None = None
    start_date: date | None = None
    target_date: date | None = None
    fields: Mapping[str, Any] | None = None

    def is_empty(self) -> bool:
        return all(getattr(self, f) is None for f in self.__dataclass_fields__ if f != "fields") and not self.fields


# --- the interface -----------------------------------------------------------


class Adapter(ABC):
    """Implement every method; raise `Unsupported` where the backend has no
    realization rather than silently dropping information."""

    backend: str

    def __init__(self, config: BoardConfig) -> None:
        self.config = config

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    # -- read ---------------------------------------------------------------

    @abstractmethod
    def describe_board(self) -> BoardDescription:
        """Read the live board and check the config against it. Also the
        write gate: implementations call it (cached) before any write and
        raise `ConfigMismatch` if it reported problems."""

    @abstractmethod
    def find_items(
        self,
        query: str = "",
        *,
        external_id: str | None = None,
        level: Level | None = None,
        state: State | None = None,
        iteration: str | None = None,
        label: str | None = None,
        limit: int = 50,
    ) -> list[WorkItem]:
        """Search the board. `external_id` is the idempotency lookup (exact);
        `query` is free text; `level` / `state` narrow the result;
        `iteration` (id or name) keeps the items whose *current* iteration
        it is, a closed one included — the read a rollover starts from;
        `label` (a name) keeps the items carrying it — the review queue."""

    @abstractmethod
    def get_item(self, ref: ItemRef | str) -> WorkItem:
        """One item by backend id or human key; `NotFound` otherwise."""

    @abstractmethod
    def get_iteration(self, iteration: str) -> Iteration:
        """One iteration by id or name, in the state the tracker reports
        now; `NotFound` otherwise."""

    # -- write --------------------------------------------------------------

    @abstractmethod
    def create_item(self, item: WorkItem) -> WorkItem:
        """Create `item` (already `check()`ed) and return it with `id`/`key`
        filled. Applies the collapse rules for unmaterialized levels."""

    @abstractmethod
    def update_item(self, ref: ItemRef | str, patch: ItemPatch) -> WorkItem: ...

    @abstractmethod
    def add_comment(self, comment: Comment) -> Comment: ...

    @abstractmethod
    def create_iteration(self, iteration: Iteration) -> Iteration:
        """Find-or-create by name: the board's iteration of that name is
        returned, never duplicated (`existing_iteration` refuses one whose
        dates differ from those given). Afterwards an iteration whose dates
        cover today is active — derived from the dates, or started where the
        tracker starts sprints explicitly."""

    @abstractmethod
    def move_to_iteration(self, items: Sequence[ItemRef | str], iteration: str) -> None:
        """Put `items` into the iteration with that id (or name)."""

    @abstractmethod
    def close_iteration(self, iteration: str) -> Iteration:
        """Mark the iteration closed. Rollover (close + move what is left)
        is composed above the adapter, not here."""
