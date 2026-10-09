"""The domain service behind the MCP server (design: agentic_optimization_research
roadmap/14 §5 layer 3, D12–D14).

The server's eleven tools are thin wrappers over `BoardService`, which
takes and returns plain JSON-ready data and does not import the MCP SDK.
The conventions live here as behavior, not prompt text. The adapter stays
mechanical (adapters/base.py).

- **Confirm = propose → commit (D12), creates only.** `propose_item`
  checks the draft against the live board, adds `labels.review` where the
  board has review on (D40) and the `external_id` (`intake_id`, or
  `intake_id/part` when one intake becomes several items), stores it for
  `DRAFT_TTL`, and returns a token and the preview. A level the board
  doesn't have (Bug on a calendar board, D39) refuses before any read. `commit_item(token)` writes exactly that draft. It looks the
  `external_id` up first, so a retried commit returns the item instead of
  duplicating it, and it finishes an iteration or feature membership that
  a failed earlier attempt left off.
- **From an intake record:** `propose_item(intake=…, part=…)` takes the
  id, level, title and placement from the record (`schema.intake`), and
  renders the description from it, so the acceptance criteria always land
  in the item body. A parent `#<part>` is that sibling part, found by its
  external_id once it is committed.
- **From a template (D41, D42):** `propose_item(template=…)` takes the
  level, feature, labels, field values and state from the board config's
  template. The request's own title, feature and dates win, and its labels
  and field values are added. With no title, the template's pattern is
  filled from the item's date. The request's description goes into the
  skeleton's `{description}` slot, and a skeleton without one refuses it.
- **Title case (D14):** a warning and a suggested title, never a reject
  (`server.titlecase`).
- **Dates and custom fields (D41):** `start_date` / `target_date` are ISO
  dates; `fields` is keyed by the config's field names, and `propose_item`
  checks each value against the board as `describe_board` read it (the
  type that carries it, its kind, its options). A retried commit fills in
  any field the failed attempt left unset, and the state when the item is
  still in `backlog` (Jira transitions after the create).
- **Errors:** every `AdapterError` becomes a `ToolFailure` whose message
  says what the agent can do about it.
- **One tracker call at a time:** the SDK runs sync tools in worker
  threads, and neither the adapter's lookup tables nor its throttle are
  thread-safe, so every operation holds one lock.
- **Several boards (D43):** `Boards` holds one `BoardService` per board,
  by name, and every tool names its board. With one board the name may be
  left out. With several, a call without one is refused, and
  `describe_board` lists them from their configs alone. `describe_board`,
  the propose result and the commit result name the board, and a token
  proposed on one board never commits on another.

Drafts live in memory. After a restart, the agent proposes again.
Nothing here deletes: work is finished by setting state `done` or `cancelled`.
"""

from __future__ import annotations

import enum
import functools
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any, Callable, Mapping, Sequence

from adapters.base import (
    Adapter,
    AdapterError,
    AuthError,
    Blocked,
    BoardDescription,
    ConfigMismatch,
    ItemPatch,
    NotFound,
    RateLimited,
    TransportError,
    Unsupported,
    ValidationError,
    field_problems,
)
from schema.intake import SIBLING, Intake, Part, render
from server import titlecase
from server.config import Template
from server.model import (
    Comment,
    InvalidWorkItem,
    ItemRef,
    Iteration,
    IterationState,
    Level,
    Materialization,
    State,
    WorkItem,
    to_jsonable,
)

DRAFT_TTL = timedelta(minutes=30)  # settled at the Phase 3 step 1 kickoff, 2026-09-23


class ToolFailure(Exception):
    """A failure the calling agent can act on; the message says what to do."""


@dataclass(frozen=True)
class Draft:
    item: WorkItem
    expires: datetime


def _explain(exc: AdapterError) -> str:
    if isinstance(exc, ConfigMismatch):
        return (
            f"The board config does not fit the live board, so nothing was written: {exc}. "
            "Fix the board config (or the board), then call describe_board to check."
        )
    if isinstance(exc, AuthError):
        return f"The tracker refused the credentials ({exc}). The operator must fix the token; retrying will not help."
    if isinstance(exc, RateLimited):
        return f"The tracker is rate-limiting ({exc}). Wait about a minute, then retry the same call."
    if isinstance(exc, Blocked):
        return (
            f"An edge wall answered instead of the tracker's API ({exc}). Wait several minutes "
            "before retrying. Retrying commit_item with the same token will not duplicate the item."
        )
    if isinstance(exc, NotFound):
        return f"Not found: {exc}. Check the key or id with find_items or get_item."
    if isinstance(exc, ValidationError):
        return f"The tracker rejected the request: {exc}. Correct it and try again."
    if isinstance(exc, Unsupported):
        return f"This board cannot do that: {exc}. describe_board lists what it can do."
    if isinstance(exc, TransportError):
        return (
            f"The tracker could not be reached ({exc}). Retry shortly. Retrying commit_item "
            "with the same token will not duplicate the item."
        )
    return f"{exc.__class__.__name__}: {exc}"


def _operation(fn):
    """Serialize the call and turn adapter and model errors into `ToolFailure`."""

    @functools.wraps(fn)
    def wrapper(self: BoardService, *args, **kwargs):
        with self._lock:
            try:
                return fn(self, *args, **kwargs)
            except AdapterError as exc:
                raise ToolFailure(_explain(exc)) from exc
            except InvalidWorkItem as exc:
                raise ToolFailure(f"The draft is not a valid work item: {exc}. Fix that and propose again.") from exc

    return wrapper


def _enum(kind: type[enum.Enum], value: str, field: str) -> Any:
    try:
        return kind(value)
    except ValueError:
        raise ToolFailure(f"{field} must be one of: {', '.join(m.value for m in kind)} (got {value!r})") from None


def _date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolFailure(f"{field} must be an ISO date like 2026-10-01 (got {value!r})") from None


def _external_id(intake_id: str, part: str) -> str:
    return f"{intake_id.strip()}/{part.strip()}" if part.strip() else intake_id.strip()


def _from_intake(data: Mapping[str, Any], part: str) -> tuple[Intake, Part]:
    """The checked record and its part, or a `ToolFailure` saying what to fix."""
    try:
        record = Intake.from_dict(data).check()
        return record, record.get_part(part)
    except (ValueError, TypeError, KeyError) as exc:
        reason = exc.args[0] if isinstance(exc, KeyError) else exc
        raise ToolFailure(f"The intake record does not work: {reason}. Fix it and propose again.") from None


def _fill(name: str, tmpl: Template, title: str, description: str, day: date | None) -> tuple[str, str]:
    """The title and description a template gives the request's own."""
    if not title.strip() and tmpl.title:
        try:
            title = tmpl.title_for(day)
        except KeyError:
            raise ToolFailure(f"Template {name!r} fills its title from the item's date: "
                              "give start_date or target_date, or a title.") from None
    if tmpl.description is not None:
        if description.strip() and not tmpl.has_slot():
            raise ToolFailure(f"Template {name!r} fixes the description, so leave description out.")
        description = tmpl.description_with(description)
    return title, description


def _match(refs, value: str, *, email: bool = False):
    """The board entry whose id, name (or email) is `value`, ignoring case."""
    want = value.lower()
    for ref in refs:
        keys = [ref.id.lower(), ref.name.lower()]
        if email and ref.extra.get("email"):
            keys.append(str(ref.extra["email"]).lower())
        if want in keys:
            return ref
    return None


class BoardService:
    def __init__(
        self,
        adapter: Adapter,
        *,
        name: str = "board",
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        ttl: timedelta = DRAFT_TTL,
    ) -> None:
        self.adapter = adapter
        self.config = adapter.config
        self.name = name
        self._clock = clock
        self._ttl = ttl
        self._lock = threading.Lock()
        self._drafts: dict[str, Draft] = {}
        self._board: BoardDescription | None = None

    def _clean_board(self) -> BoardDescription:
        """The board as last read (read now if never), refusing if the config doesn't fit it."""
        if self._board is None:
            self._board = self.adapter.describe_board()
        return self._board.check()

    def holds(self, token: str) -> bool:
        """Whether this board has a live draft under `token`."""
        return token in self._drafts

    def summary(self) -> dict[str, Any]:
        """The board as its config describes it, without reading the tracker."""
        cfg = self.config
        return {
            "board": self.name,
            "description": cfg.description,
            "backend": cfg.backend.value,
            "board_type": cfg.board_type.value,
            "project": cfg.connection.ids.get("project_key") or cfg.connection.ids.get("project"),
        }

    # -- reads ------------------------------------------------------------------

    @_operation
    def describe_board(self) -> dict[str, Any]:
        self._board = self.adapter.describe_board()
        cfg = self.config
        return {
            "board": self.name,
            "description": cfg.description,
            **to_jsonable(self._board),
            "capabilities": to_jsonable(self.adapter.capabilities),
            "board_type": cfg.board_type.value,
            "confirm": cfg.confirm.value,
            "review_label": cfg.labels.review,  # None: review is off on this board (D40)
            "label_taxonomy": list(cfg.labels.taxonomy),
            "naming": {"iteration": cfg.naming.iteration, "item_case": cfg.naming.item_case.value},
            "templates": to_jsonable(cfg.templates),
        }

    @_operation
    def find_items(
        self,
        query: str = "",
        *,
        external_id: str | None = None,
        level: str | None = None,
        state: str | None = None,
        iteration: str | None = None,
        label: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        items = self.adapter.find_items(
            query,
            external_id=external_id or None,
            level=_enum(Level, level, "level") if level else None,
            state=_enum(State, state, "state") if state else None,
            iteration=iteration or None,
            label=label or None,
            limit=limit,
        )
        return to_jsonable(items)

    @_operation
    def get_item(self, ref: str) -> dict[str, Any]:
        return to_jsonable(self.adapter.get_item(ref))

    @_operation
    def get_iteration(self, iteration: str) -> dict[str, Any]:
        return to_jsonable(self.adapter.get_iteration(iteration))

    # -- the confirm step (D12) -------------------------------------------------

    @_operation
    def propose_item(
        self,
        intake_id: str = "",
        level: str = "",
        title: str = "",
        description: str = "",
        *,
        intake: Mapping[str, Any] | None = None,
        part: str = "",
        template: str = "",
        parent: str | None = None,
        feature: str | None = None,
        initiative: str | None = None,
        component: str | None = None,
        iteration: str | None = None,
        assignees: Sequence[str] = (),
        labels: Sequence[str] = (),
        start_date: str | None = None,
        target_date: str | None = None,
        fields: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        start, target = _date(start_date, "start_date"), _date(target_date, "target_date")
        cfg = self.config
        tmpl = None
        if template:
            tmpl = cfg.templates.get(template)
            if intake is not None:
                raise ToolFailure("Pass an intake record or a template, not both.")
            if tmpl is None:
                have = ", ".join(cfg.templates) or "(none)"
                raise ToolFailure(f"No template {template!r} in the board config (templates: {have}).")
            if level:
                raise ToolFailure(f"Template {template!r} supplies the level ({tmpl.level.value}); leave level out.")
            level = tmpl.level.value
            title, description = _fill(template, tmpl, title, description, start or target)
            feature = feature or tmpl.feature
            given = {name.lower() for name in labels}
            labels = [*(name for name in tmpl.labels if name.lower() not in given), *labels]
            fields = {**tmpl.fields, **(fields or {})}
        if intake is not None:
            given = {"intake_id": intake_id, "level": level, "title": title, "description": description,
                     "parent": parent, "feature": feature, "iteration": iteration}
            if any(given.values()):
                named = ", ".join(k for k, v in given.items() if v)
                raise ToolFailure(f"With an intake record, the record supplies {named}; leave them out.")
            record, chosen = _from_intake(intake, part)
            intake_id, level, title = record.id, chosen.level.value, chosen.title
            description = render(record, part)
            parent, feature, iteration = (chosen.placement.parent, chosen.placement.feature,
                                          chosen.placement.iteration)
        if not intake_id.strip():
            raise ToolFailure("intake_id is required: it is the idempotency key's root")
        lvl = _enum(Level, level, "level")
        if lvl not in cfg.levels:
            raise ToolFailure(
                f"This {cfg.board_type.value} board has no {lvl.value} level, so nothing can be filed as one. "
                "File the work as a story instead, or as a task under one."
            )
        board = self._clean_board()
        problems: list[str] = []

        parent_ref = parent_item = None
        if parent and parent.startswith(SIBLING):
            sibling = self.adapter.find_items(external_id=_external_id(intake_id, parent[1:]))
            if not sibling:
                raise ToolFailure(
                    f"Part {parent[1:]!r} of intake {intake_id.strip()!r} is not on the board yet. "
                    "Commit it first, then propose this part."
                )
            parent_item = sibling[0]
        elif parent:
            parent_item = self.adapter.get_item(parent)
        if parent_item is not None:
            parent_ref = ItemRef(parent_item.id or parent, parent_item.level, parent_item.key)

        feature_ref = feature_name = None
        if feature:
            if cfg.levels[Level.FEATURE].how is Materialization.CONTAINER:
                hit = _match(board.containers, feature)
                if hit is None:
                    have = ", ".join(c.name for c in board.containers) or "(none)"
                    problems.append(f"no feature {feature!r} on the board (features: {have})")
                else:
                    feature_ref, feature_name = ItemRef(hit.id, Level.FEATURE), hit.name
            else:  # collapsed: the adapter writes it as a label or description line
                feature_ref, feature_name = ItemRef(feature, Level.FEATURE), feature

        cycle = None
        if iteration:
            cycle = self.adapter.get_iteration(iteration)
            if cycle.state is IterationState.CLOSED:
                problems.append(f"iteration {cycle.name!r} is closed; pick an open one or leave it out")

        wanted = list(labels)
        review = cfg.labels.review
        if review and review.lower() not in {name.lower() for name in wanted}:
            wanted.append(review)
        missing = [name for name in wanted if _match(board.labels, name) is None]
        if missing:
            have = ", ".join(l.name for l in board.labels) or "(none)"
            problems.append(f"labels not on the board: {', '.join(missing)} (labels: {have})")
        unknown = [who for who in assignees if _match(board.members, who, email=True) is None]
        if unknown:
            have = ", ".join(m.name for m in board.members) or "(none)"
            problems.append(f"assignees not in the workspace: {', '.join(unknown)} (members: {have})")
        problems += field_problems(board, lvl, fields or {})

        external_id = _external_id(intake_id, part)
        item = WorkItem(
            level=lvl,
            title=title,
            description=description,
            parent=parent_ref,
            feature=feature_ref,
            initiative=ItemRef(initiative, Level.INITIATIVE) if initiative else None,
            component=component or None,
            iteration=cycle.id if cycle else None,
            state=tmpl.state if tmpl else State.BACKLOG,
            assignees=tuple(assignees),
            labels=tuple(wanted),
            external_id=external_id,
            start_date=start,
            target_date=target,
            fields=dict(fields or {}),
        )
        problems += item.validate()
        if problems:
            raise ToolFailure(f"The draft does not fit the board: {'; '.join(problems)}. Fix that and propose again.")

        warnings: list[str] = []
        suggested = titlecase.suggest(title, cfg.naming.item_case)
        if suggested:
            warnings.append(
                f"The title is not {cfg.naming.item_case.value} case; suggested: {suggested!r}. "
                "To use it, propose again with that title."
            )
        existing = self.adapter.find_items(external_id=external_id)
        if existing:
            warnings.append(
                f"{existing[0].key or existing[0].id} already has external_id {external_id!r}; "
                "commit_item returns it instead of creating a duplicate."
            )

        now = self._clock()
        self._drafts = {t: d for t, d in self._drafts.items() if d.expires > now}
        token = token_urlsafe(9)
        expires = now + self._ttl
        self._drafts[token] = Draft(item, expires)
        preview = to_jsonable(item)
        preview["parent"] = (
            {"id": parent_item.id, "key": parent_item.key, "level": parent_item.level.value, "title": parent_item.title}
            if parent_item else None
        )
        preview["feature"] = {"id": feature_ref.id, "name": feature_name} if feature_ref else None
        preview["iteration"] = {"id": cycle.id, "name": cycle.name} if cycle else None
        return {
            "board": self.name,
            "token": token,
            "expires_at": expires.isoformat(),
            "confirm": cfg.confirm.value,
            "preview": preview,
            "warnings": warnings,
            "suggested_title": suggested,
            "existing": to_jsonable(existing[0]) if existing else None,
        }

    @_operation
    def commit_item(self, token: str) -> dict[str, Any]:
        draft = self._drafts.get(token)
        if draft is None:
            raise ToolFailure("Unknown draft token (the server may have restarted). Call propose_item again.")
        if self._clock() >= draft.expires:
            del self._drafts[token]
            raise ToolFailure(
                f"The draft expired at {draft.expires.isoformat()}. Call propose_item again "
                "so the requester confirms against the board as it is now."
            )
        item = draft.item
        found = self.adapter.find_items(external_id=item.external_id)
        if not found:
            return {"board": self.name, "item": to_jsonable(self.adapter.create_item(item)), "already_existed": False}
        # A retry: the item exists. Finish what a failed attempt may have left off.
        current = found[0]
        ref = current.id or ""
        if item.feature is not None and current.feature is None \
                and self.config.levels[Level.FEATURE].how is Materialization.CONTAINER:
            self.adapter.update_item(ref, ItemPatch(feature=item.feature))
        if item.iteration and current.iteration is None:
            self.adapter.move_to_iteration([ref], item.iteration)
        now = self.adapter.get_item(ref)
        # Plane writes values after the item, and Jira moves it out of its first status
        # after the create: a failed attempt may have left either off.
        unset = {name: value for name, value in item.fields.items() if name not in now.fields}
        state = item.state if now.state is State.BACKLOG and item.state is not State.BACKLOG else None
        if unset or state:
            now = self.adapter.update_item(ref, ItemPatch(fields=unset or None, state=state))
        return {"board": self.name, "item": to_jsonable(now), "already_existed": True}

    # -- other writes -----------------------------------------------------------

    @_operation
    def update_item(
        self,
        ref: str,
        *,
        title: str | None = None,
        description: str | None = None,
        state: str | None = None,
        assignees: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
        parent: str | None = None,
        feature: str | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
        fields: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        patch = ItemPatch(
            title=title,
            description=description,
            state=_enum(State, state, "state") if state else None,
            assignees=tuple(assignees) if assignees is not None else None,
            labels=tuple(labels) if labels is not None else None,
            parent=ItemRef(parent) if parent else None,
            feature=ItemRef(feature, Level.FEATURE) if feature else None,
            start_date=_date(start_date, "start_date"),
            target_date=_date(target_date, "target_date"),
            fields=dict(fields) if fields else None,
        )
        return to_jsonable(self.adapter.update_item(ref, patch))

    @_operation
    def add_comment(self, ref: str, body: str) -> dict[str, Any]:
        if not body.strip():
            raise ToolFailure("The comment body is empty.")
        return to_jsonable(self.adapter.add_comment(Comment(ItemRef(ref), body)))

    @_operation
    def create_iteration(self, name: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        it = Iteration(name, start=_date(start, "start"), end=_date(end, "end"))
        return to_jsonable(self.adapter.create_iteration(it))

    @_operation
    def move_to_iteration(self, items: Sequence[str], iteration: str) -> dict[str, Any]:
        self.adapter.move_to_iteration(list(items), iteration)
        return {"moved": list(items), "iteration": iteration}

    @_operation
    def close_iteration(self, iteration: str) -> dict[str, Any]:
        return to_jsonable(self.adapter.close_iteration(iteration))


class Boards:
    """Every board one server serves, by name (D43). Read-only after start,
    so it needs no lock of its own; each board's service keeps its own."""

    def __init__(self, services: Sequence[BoardService]) -> None:
        self._services = {svc.name: svc for svc in services}

    def _names(self) -> str:
        return ", ".join(self._services)

    def get(self, board: str | None) -> BoardService:
        """The named board, or the only one when no name is given."""
        if board and board.strip():
            want = board.strip().lower()
            for name, svc in self._services.items():
                if name.lower() == want:
                    return svc
            raise ToolFailure(f"No board {board!r} on this server (boards: {self._names()}).")
        if len(self._services) == 1:
            return next(iter(self._services.values()))
        raise ToolFailure(
            f"This server serves several boards ({self._names()}), so every call names one: pass board. "
            "describe_board with no board lists them."
        )

    def describe_board(self, board: str | None) -> dict[str, Any]:
        if not (board and board.strip()) and len(self._services) > 1:
            return {"boards": [svc.summary() for svc in self._services.values()]}
        return self.get(board).describe_board()

    def commit_item(self, token: str, board: str | None) -> dict[str, Any]:
        svc = self.get(board)
        if not svc.holds(token):
            other = next((s.name for s in self._services.values() if s is not svc and s.holds(token)), None)
            if other is not None:
                raise ToolFailure(
                    f"That draft was proposed on board {other!r}, not {svc.name!r}, so nothing was written. "
                    "Confirm the board with the requester, then propose on that board."
                )
        return svc.commit_item(token)
