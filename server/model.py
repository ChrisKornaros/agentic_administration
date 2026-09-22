"""The canonical work-item model — the only shape skills, the MCP server and
the chat runtime ever see (design: agentic_optimization_research
roadmap/14 §4 and §8).

Levels: Initiative > Epic > Feature > Story / Bug > Task. The chain the
model *guarantees* is Epic > Story / Bug > Task, expressed through
`WorkItem.parent`. Initiative and Feature are optional levels and are
modelled as **attachments**, not links in the parent chain: an epic may
name its `initiative`, a story or bug may name its `feature`. Decomposition
rules are written for the three-level core, so nothing here assumes the
optional levels exist on a given backend.

Descriptions are Markdown — the source of truth. Each adapter renders it
into the tracker's format (Plane HTML, Jira ADF, ADO HTML).

`assignees` are opaque identifiers the adapter resolves against the board's
member directory; the model does not know whether they are names or ids.

Nothing here talks to a tracker, and there is no delete anywhere in the
model: an item's terminal states are `done` and `cancelled`.

Every record is exportable as plain JSON via `to_jsonable` (the
knowledge-graph seam from roadmap/14 §8): a graph loader consumes that
export, the model does not change for it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from typing import Any, Mapping


# --- levels and states -----------------------------------------------------


class Level(enum.Enum):
    INITIATIVE = "initiative"
    EPIC = "epic"
    FEATURE = "feature"
    STORY = "story"
    BUG = "bug"
    TASK = "task"


CORE_LEVELS: frozenset[Level] = frozenset({Level.EPIC, Level.STORY, Level.BUG, Level.TASK})
OPTIONAL_LEVELS: frozenset[Level] = frozenset({Level.INITIATIVE, Level.FEATURE})

# Which levels an item's `parent` may be. Empty = the item never has a parent.
PARENT_LEVELS: Mapping[Level, frozenset[Level]] = {
    Level.INITIATIVE: frozenset(),
    Level.EPIC: frozenset(),  # the initiative is an attachment, not a parent
    Level.FEATURE: frozenset({Level.EPIC}),
    Level.STORY: frozenset({Level.EPIC}),
    Level.BUG: frozenset({Level.EPIC}),
    Level.TASK: frozenset({Level.STORY, Level.BUG}),
}

# Levels whose items *must* have a parent (the smallest unit never floats).
PARENT_REQUIRED: frozenset[Level] = frozenset({Level.TASK})

# Where each attachment may sit.
FEATURE_ATTACHES_TO: frozenset[Level] = frozenset({Level.STORY, Level.BUG})
INITIATIVE_ATTACHES_TO: frozenset[Level] = frozenset({Level.EPIC})


class State(enum.Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class IterationState(enum.Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    CLOSED = "closed"


# --- records ---------------------------------------------------------------


@dataclass(frozen=True)
class ItemRef:
    """A reference to a work item that already exists on the board.

    `id` is the backend's identifier. `level` is carried when known so the
    model can check placement without a round-trip; `key` is the human key
    (e.g. `AOR-12`) when the backend has one.
    """

    id: str
    level: Level | None = None
    key: str | None = None


class InvalidWorkItem(ValueError):
    """Raised by `WorkItem.check()`; `.problems` lists every violation."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class WorkItem:
    level: Level
    title: str
    description: str = ""  # Markdown — the source of truth
    id: str | None = None  # None until the adapter has created it
    key: str | None = None
    parent: ItemRef | None = None
    initiative: ItemRef | None = None  # attachment: epics only
    feature: ItemRef | None = None  # attachment: stories and bugs only
    state: State = State.BACKLOG
    assignees: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    iteration: str | None = None  # an Iteration.id
    component: str | None = None  # the cross-cutting axis, never a level
    external_id: str | None = None  # the idempotency key, when the caller has one
    related: tuple[ItemRef, ...] = ()
    links: tuple[str, ...] = ()

    def validate(self) -> list[str]:
        """Return every placement/shape violation; empty means valid."""
        problems: list[str] = []
        if not self.title.strip():
            problems.append("title is empty")

        allowed = PARENT_LEVELS[self.level]
        if self.parent is None:
            if self.level in PARENT_REQUIRED:
                names = " or ".join(sorted(lv.value for lv in allowed))
                problems.append(f"a {self.level.value} must have a parent ({names})")
        elif not allowed:
            problems.append(f"a {self.level.value} never has a parent")
        elif self.parent.level is not None and self.parent.level not in allowed:
            names = " or ".join(sorted(lv.value for lv in allowed))
            problems.append(
                f"a {self.level.value} cannot be parented under a "
                f"{self.parent.level.value} (allowed: {names})"
            )

        if self.feature is not None:
            if self.level not in FEATURE_ATTACHES_TO:
                problems.append(f"a {self.level.value} cannot carry a feature")
            elif self.feature.level not in (None, Level.FEATURE):
                problems.append(f"feature ref points at a {self.feature.level.value}")
        if self.initiative is not None:
            if self.level not in INITIATIVE_ATTACHES_TO:
                problems.append(f"a {self.level.value} cannot carry an initiative")
            elif self.initiative.level not in (None, Level.INITIATIVE):
                problems.append(
                    f"initiative ref points at a {self.initiative.level.value}"
                )
        return problems

    def check(self) -> WorkItem:
        """Raise `InvalidWorkItem` if `validate()` finds anything; else return self."""
        problems = self.validate()
        if problems:
            raise InvalidWorkItem(problems)
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkItem:
        """Inverse of `to_jsonable(item)`. Unknown keys are an error."""
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown WorkItem fields: {', '.join(unknown)}")
        kw: dict[str, Any] = dict(data)
        kw["level"] = Level(kw["level"])
        if "state" in kw:
            kw["state"] = State(kw["state"])
        for ref in ("parent", "initiative", "feature"):
            if kw.get(ref) is not None:
                kw[ref] = _ref_from_dict(kw[ref])
        for seq in ("assignees", "labels", "links"):
            if seq in kw:
                kw[seq] = tuple(kw[seq])
        if "related" in kw:
            kw["related"] = tuple(_ref_from_dict(r) for r in kw["related"])
        return cls(**kw)


def _ref_from_dict(data: Mapping[str, Any]) -> ItemRef:
    level = data.get("level")
    return ItemRef(
        id=data["id"],
        level=Level(level) if level is not None else None,
        key=data.get("key"),
    )


@dataclass
class Iteration:
    """A sprint / cycle. `id` is None until created."""

    name: str
    id: str | None = None
    start: date | None = None
    end: date | None = None
    state: IterationState = IterationState.PLANNED


@dataclass
class Comment:
    item: ItemRef
    body: str  # Markdown
    id: str | None = None
    author: str | None = None
    created_at: datetime | None = None


# --- what an adapter can do ------------------------------------------------


class Materialization(enum.Enum):
    """How a backend realizes a canonical level as something referenceable."""

    TYPE = "type"  # a native work-item type (Plane Epic, Jira Story)
    PARENT = "parent"  # a parent link plus a `type:<level>` label (D4 fallback)
    CONTAINER = "container"  # membership in a grouping object (Plane module = Feature)
    LABEL = "label"  # a label alone marks the level
    NONE = "none"  # not materialized — see the collapse rule


class CollapseTarget(enum.Enum):
    """Where an unmaterialized level's information goes so nothing is lost."""

    LABEL = "label"
    COMPONENT = "component"
    DESCRIPTION_LINE = "description_line"


@dataclass(frozen=True)
class CollapseRule:
    target: CollapseTarget
    # e.g. "initiative:{name}" for a label, "**Initiative:** {name}" for a line
    template: str = "{level}:{name}"


class DescriptionFormat(enum.Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    ADF = "adf"  # Atlassian Document Format


@dataclass(frozen=True)
class Capabilities:
    """Declared by every adapter; skills read it before acting.

    `levels` covers all six levels. A level marked `Materialization.NONE`
    must have a `collapse` rule, and only those levels may.
    """

    backend: str
    levels: Mapping[Level, Materialization]
    description_format: DescriptionFormat
    states_via_transitions: bool  # Jira: yes; Plane, ADO: no
    native_idempotency_key: bool  # Plane `external_id`: yes; Jira: no
    move_to_iteration_is_separate_call: bool = True  # true on all three
    collapse: Mapping[Level, CollapseRule] = field(default_factory=dict)

    def __post_init__(self) -> None:
        missing = sorted(lv.value for lv in Level if lv not in self.levels)
        if missing:
            raise ValueError(f"capabilities for {self.backend} miss levels: {', '.join(missing)}")
        unmaterialized = {lv for lv, how in self.levels.items() if how is Materialization.NONE}
        no_rule = sorted(lv.value for lv in unmaterialized - set(self.collapse))
        if no_rule:
            raise ValueError(f"unmaterialized levels without a collapse rule: {', '.join(no_rule)}")
        stray = sorted(lv.value for lv in set(self.collapse) - unmaterialized)
        if stray:
            raise ValueError(f"collapse rules for materialized levels: {', '.join(stray)}")

    def materializes(self, level: Level) -> bool:
        return self.levels[level] is not Materialization.NONE


# --- export ----------------------------------------------------------------


def to_jsonable(obj: Any) -> Any:
    """Recursively convert model records into plain JSON-serializable data.

    Enums become their `.value`, dates and datetimes their ISO string,
    dataclasses dicts, tuples lists, enum-keyed mappings string-keyed dicts.
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Mapping):
        return {to_jsonable(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in obj]
    return obj
