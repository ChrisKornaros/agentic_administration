"""The intake record and its Markdown rendering (design:
agentic_optimization_research roadmap/14 §7 and §8).

The template is not the product; the conversation is. A requester says two
sentences, the agent asks until the record is full, and `render` turns it
into the Markdown `description` an item carries. The fields are the top half
of AOR's requirement-intake template; its Triage half stays in the vault.

One intake is one request. Its shared context (`problem`, `outcome`,
`constraints`, `urgency`, `related`) is written once, and `parts` are the
items it becomes. A request that fits one item is one part with the empty
name; a split (an epic plus its stories) names every part. A part's
external_id is `id/part`, or `id` for the unnamed part, so
`propose_item(intake=…, part=…)` turns one part into one item.

A part's `placement.parent` is an existing item's key or id, or `#<part>`
for a sibling part, which the server finds by that part's external_id once
it is committed. Placement rules are the model's (`WorkItem.validate`).

Nothing here talks to a tracker. Every record exports as plain JSON via
`server.model.to_jsonable` (the §8 seam).
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field, fields
from typing import Any, Mapping

from server.model import ItemRef, Level, WorkItem

NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")  # an intake id or a part name: no "/", which joins them
SIBLING = "#"  # placement.parent "#epic" = the part named "epic" in the same intake
NEEDS_ACCEPTANCE: frozenset[Level] = frozenset({Level.STORY, Level.BUG})


class Urgency(enum.Enum):
    """The requester's gut feel. It does not bind the PM, who orders the backlog."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Criterion:
    """One acceptance criterion: agent-drafted, requester-confirmed."""

    given: str
    when: str
    then: str


@dataclass(frozen=True)
class Placement:
    """Where a part lands, proposed from the board's live state. `parent` is
    an existing item's key or id, or `#<part>` for a sibling part; `feature`
    names one of the board's features; `iteration` is an open iteration."""

    parent: str | None = None
    feature: str | None = None
    iteration: str | None = None


@dataclass(frozen=True)
class Part:
    """One item the intake becomes. `part` is empty when the intake is one
    item, and names every part of a split. A story or bug needs acceptance
    criteria."""

    level: Level
    title: str
    part: str = ""
    acceptance: tuple[Criterion, ...] = ()
    placement: Placement = field(default_factory=Placement)


class InvalidIntake(ValueError):
    """Raised by `Intake.check()`; `.problems` lists every violation."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Intake:
    """One request, as the intake conversation filled it. `id` is stable for
    the request's life (the idempotency key's root); `problem` is the need and
    who feels it; `outcome` is what done looks like, in the requester's words;
    `related` holds item keys, or the requester's words when no key was found."""

    id: str
    problem: str
    outcome: str
    constraints: tuple[str, ...] = ()
    urgency: Urgency | None = None
    related: tuple[str, ...] = ()
    parts: tuple[Part, ...] = ()

    def get_part(self, name: str = "") -> Part:
        for p in self.parts:
            if p.part == name:
                return p
        have = ", ".join(repr(p.part) for p in self.parts) or "(none)"
        raise KeyError(f"intake {self.id!r} has no part {name!r} (parts: {have})")

    def validate(self) -> list[str]:
        """Return every problem with the record; empty means valid."""
        problems: list[str] = []
        if not NAME.fullmatch(self.id):
            problems.append(f"id {self.id!r} must be 1-64 letters, digits, '.', '_' or '-'")
        for name in ("problem", "outcome"):
            if not getattr(self, name).strip():
                problems.append(f"{name} is empty")
        if any(not c.strip() for c in self.constraints):
            problems.append("a constraint is empty")
        if any(not r.strip() for r in self.related):
            problems.append("a related entry is empty")
        if not self.parts:
            problems.append("an intake needs at least one part")
        names = [p.part for p in self.parts]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            problems.append(f"part names repeat: {', '.join(map(repr, repeated))}")
        for p in self.parts:
            problems += [f"part {p.part!r}: {msg}" for msg in self._part_problems(p)]
        return problems

    def _part_problems(self, p: Part) -> list[str]:
        problems: list[str] = []
        if p.part and not NAME.fullmatch(p.part):
            problems.append("the name must be 1-64 letters, digits, '.', '_' or '-'")
        if not p.part and len(self.parts) > 1:
            problems.append("needs a name: the intake has several parts")
        if p.level in NEEDS_ACCEPTANCE and not p.acceptance:
            problems.append(f"a {p.level.value} needs at least one acceptance criterion")
        for i, c in enumerate(p.acceptance, 1):
            empty = [n for n in ("given", "when", "then") if not getattr(c, n).strip()]
            if empty:
                problems.append(f"acceptance {i} has an empty {' / '.join(empty)}")

        target = p.placement.parent
        parent = ItemRef(target) if target else None
        if target and target.startswith(SIBLING):
            sibling = next((s for s in self.parts if s.part == target[1:] and s is not p), None)
            if sibling is None:
                problems.append(f"parent {target!r} names no other part of this intake")
            else:
                parent = ItemRef(target, sibling.level)
        feature = ItemRef(p.placement.feature, Level.FEATURE) if p.placement.feature else None
        return problems + WorkItem(p.level, p.title, parent=parent, feature=feature).validate()

    def check(self) -> Intake:
        """Raise `InvalidIntake` if `validate()` finds anything; else return self."""
        problems = self.validate()
        if problems:
            raise InvalidIntake(problems)
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Intake:
        """Inverse of `to_jsonable(intake)`. Unknown keys are an error."""
        kw = _known(cls, data)
        if kw.get("urgency") is not None:
            kw["urgency"] = Urgency(kw["urgency"])
        for seq in ("constraints", "related"):
            if seq in kw:
                kw[seq] = tuple(kw[seq])
        kw["parts"] = tuple(_part_from_dict(p) for p in kw.get("parts", ()))
        return cls(**kw)


def _known(cls: type, data: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(data) - {f.name for f in fields(cls)})
    if unknown:
        raise ValueError(f"unknown {cls.__name__} fields: {', '.join(unknown)}")
    return dict(data)


def _part_from_dict(data: Mapping[str, Any]) -> Part:
    kw = _known(Part, data)
    kw["level"] = Level(kw["level"])
    kw["acceptance"] = tuple(Criterion(**_known(Criterion, c)) for c in kw.get("acceptance", ()))
    if kw.get("placement") is not None:
        kw["placement"] = Placement(**_known(Placement, kw["placement"]))
    else:
        kw.pop("placement", None)
    return Part(**kw)


# --- the Markdown rendering ------------------------------------------------


def _line(text: str) -> str:
    """One list line: runs of whitespace (newlines too) become single spaces."""
    return " ".join(text.split())


def render(intake: Intake, part: str = "") -> str:
    """The Markdown description of one part: the request's shared context,
    then that part's acceptance criteria. It uses only the Markdown every
    adapter renders (headings, paragraphs, lists, inline marks): no tables,
    no rules."""
    p = intake.get_part(part)
    blocks = [f"## Problem\n\n{intake.problem.strip()}", f"## Outcome\n\n{intake.outcome.strip()}"]
    if p.acceptance:
        blocks.append("## Acceptance criteria\n\n" + "\n".join(
            f"{i}. **Given** {_line(c.given).rstrip('.,;')}, **when** {_line(c.when).rstrip('.,;')}, "
            f"**then** {_line(c.then)}"
            for i, c in enumerate(p.acceptance, 1)
        ))
    if intake.constraints:
        blocks.append("## Constraints\n\n" + "\n".join(f"- {_line(c)}" for c in intake.constraints))
    if intake.related:
        blocks.append("## Related\n\n" + "\n".join(f"- {_line(r)}" for r in intake.related))
    footer = f"Intake `{intake.id}`" + (f", part `{p.part}`" if p.part else "")
    if intake.urgency is not None:
        footer += f" · urgency (the requester's): {intake.urgency.value}"
    return "\n\n".join(blocks + [footer]) + "\n"
