"""The Plane Cloud adapter (design: roadmap/14 §4 D3, §5; live findings §3.1).

How the canonical model lands on Plane:

- Epic / Story / Bug / Task are **work-item types** (`type_id`), named per
  level in the board config; the parent chain is the item's `parent`.
- Feature = **module membership** (D3): a story's `feature` is the module
  it is added to, never a parent link. `component` is module membership
  too — Plane has one grouping object and the two axes share it.
- Initiative is read-only in v1 (Plane's initiatives sit above projects);
  an epic's `initiative` attachment goes wherever the config's collapse
  rule says (label / module / description line).
- States are set directly (no transitions); the config maps canonical
  states to the board's state *names*, resolved to ids on `describe_board`.
- `external_id` + a fixed `external_source` is the idempotency key;
  `find_items(external_id=…)` is the project list's lookup on both (one
  record or 404). The workspace search ignores them (conformance,
  2026-09-22); it serves free-text `query` only.
- Every route ends in `/`: Plane 301s a slash-less one, and a redirected
  write is never re-sent.
- Descriptions and comments are Markdown in, Plane HTML out
  (`adapters.plane.markdown`).

Read-proven-before-write: every route here was read live in Phase 1
(probes/plane_phase1_readonly.py) and written live by the conformance
suite against a throwaway project (conformance/README.md, 2026-09-22).
Iteration close relies on Plane's rule that a cycle is completed once
its `end_date` is *before* today — one ending today is still current.
`create_iteration` is find-or-create by name (Phase 6), and
`find_items(iteration=…)` reads the cycle's own `cycle-issues/` list.

No delete: there is no DELETE request in this file, and moving an item
between modules only *adds* membership.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from adapters.base import (
    Adapter,
    BoardDescription,
    ItemPatch,
    NamedRef,
    NotFound,
    StateInfo,
    TransportError,
    TypeInfo,
    Unsupported,
    ValidationError,
    existing_iteration,
)
from adapters.plane import markdown
from adapters.plane.transport import PlaneTransport, Transport
from server import secrets
from server.config import Backend, BoardConfig
from server.model import (
    Capabilities,
    CollapseRule,
    CollapseTarget,
    Comment,
    DescriptionFormat,
    ItemRef,
    Iteration,
    IterationState,
    Level,
    Materialization,
    State,
    WorkItem,
)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Plane's state buckets line up with the canonical states one-to-one; used
# to read an item whose state id the config did not name.
_GROUP_TO_STATE = {
    "backlog": State.BACKLOG,
    "unstarted": State.TODO,
    "started": State.IN_PROGRESS,
    "completed": State.DONE,
    "cancelled": State.CANCELLED,
}
_CYCLE_STATUS = {"completed": IterationState.CLOSED, "current": IterationState.ACTIVE}


class PlaneAdapter(Adapter):
    backend = "plane"
    EXTERNAL_SOURCE = "agentic_administration"

    def __init__(
        self,
        config: BoardConfig,
        transport: Transport | None = None,
        *,
        secret: Callable[[str], str] = secrets.get,
        today: Callable[[], date] = date.today,
    ) -> None:
        if config.backend is not Backend.PLANE:
            raise ValueError(f"PlaneAdapter got a {config.backend.value} config")
        super().__init__(config)
        conn = config.connection
        self.slug = conn.ids["workspace"]
        self._project_ref = conn.ids["project"]
        self._t: Transport = transport or PlaneTransport(
            lambda: secret(conn.token_env), base_url=conn.base_url
        )
        self._today = today
        self._caps = Capabilities(
            self.backend,
            config.materializations(),
            DescriptionFormat.HTML,
            states_via_transitions=False,
            native_idempotency_key=True,
            collapse=config.collapse_rules(),
        )
        self._project: dict[str, Any] | None = None
        self._board: BoardDescription | None = None
        # lookup tables filled by describe_board
        self._level_of_type: dict[str, Level] = {}
        self._level_of_label: dict[str, Level] = {}  # marker label id -> LABEL/PARENT level
        self._type_is_epic: dict[str, bool] = {}
        self._state_id: dict[State, str] = {}
        self._state_of_id: dict[str, State] = {}
        self._labels: dict[str, str] = {}  # lower name / id -> id
        self._label_name: dict[str, str] = {}
        self._members: dict[str, str] = {}  # lower name / email / id -> id
        self._member_name: dict[str, str] = {}
        self._modules: dict[str, str] = {}  # lower name / id -> id
        self._cycles: dict[str, str] = {}  # name / id -> id

    # -- plumbing ------------------------------------------------------------------

    @property
    def capabilities(self) -> Capabilities:
        return self._caps

    @property
    def _ws(self) -> str:
        return f"/workspaces/{self.slug}"

    @property
    def _pp(self) -> str:
        return f"{self._ws}/projects/{self.project['id']}"

    @property
    def project(self) -> dict[str, Any]:
        """The project record; `connection.project` may be the UUID, the
        identifier (`AA`) or the name — resolved once via the project list."""
        if self._project is None:
            ref = self._project_ref
            for p in self._t.get_all(f"{self._ws}/projects/"):
                if ref in (p.get("id"), p.get("identifier")) or ref.lower() == (p.get("name") or "").lower():
                    self._project = p
                    break
            else:
                raise NotFound(f"no project {ref!r} in workspace {self.slug!r}")
        return self._project

    def _ready(self) -> BoardDescription:
        """The write gate: the cached board description, clean."""
        if self._board is None:
            self.describe_board()
        assert self._board is not None
        return self._board.check()

    # -- describe ------------------------------------------------------------------

    def describe_board(self) -> BoardDescription:
        proj = self.project
        pp, ws = self._pp, self._ws
        features = self._t.request("GET", f"{pp}/features/") or {}
        types = [
            TypeInfo(t["id"], t.get("name") or "", bool(t.get("is_epic")),
                     bool(t.get("is_default") or t.get("is_default_in_project")))
            for t in self._t.get_all(f"{pp}/work-item-types/")
        ]
        states = [StateInfo(s["id"], s.get("name") or "", s.get("group")) for s in self._t.get_all(f"{pp}/states/")]
        labels = [NamedRef(l["id"], l.get("name") or "") for l in self._t.get_all(f"{pp}/labels/")]
        members = [
            NamedRef(m["id"], m.get("display_name") or m.get("email") or m["id"],
                     {"email": m.get("email"), "role": m.get("role")})
            for m in self._t.get_all(f"{ws}/members-lite/")
        ]
        modules = [NamedRef(m["id"], m.get("name") or "") for m in self._t.get_all(f"{pp}/modules/")]
        cycles = [
            NamedRef(c["id"], c.get("name") or "",
                     {"start": c.get("start_date"), "end": c.get("end_date"), "status": c.get("status")})
            for c in self._t.get_all(f"{pp}/cycles/")
        ]

        self._index(types, states, labels, members, modules, cycles)
        resolved, problems = self._check_config(features, types, states, labels)
        self._board = BoardDescription(
            backend=self.backend,
            project_id=proj["id"],
            project_key=proj.get("identifier"),
            project_name=proj.get("name"),
            features=dict(features) if isinstance(features, dict) else {},
            types=tuple(types),
            states=tuple(states),
            labels=tuple(labels),
            members=tuple(members),
            containers=tuple(modules),
            iterations=tuple(cycles),
            resolved=resolved,
            problems=tuple(problems),
        )
        return self._board

    def _index(self, types, states, labels, members, modules, cycles) -> None:
        self._type_is_epic = {t.id: t.is_epic for t in types}
        self._labels = {}
        self._label_name = {}
        for l in labels:
            self._labels[l.id] = l.id
            self._labels[l.name.lower()] = l.id
            self._label_name[l.id] = l.name
        self._members = {}
        self._member_name = {}
        for m in members:
            self._members[m.id] = m.id
            self._members[m.name.lower()] = m.id
            if m.extra.get("email"):
                self._members[str(m.extra["email"]).lower()] = m.id
            self._member_name[m.id] = m.name
        self._modules = {}
        for m in modules:
            self._modules[m.id] = m.id
            self._modules[m.name.lower()] = m.id
        self._cycles = {}
        for c in cycles:
            self._cycles[c.id] = c.id
            self._cycles[c.name] = c.id
        # state ids: the config's names first, then Plane's groups as the read fallback
        self._state_of_id = {}
        for s in states:
            if s.group in _GROUP_TO_STATE:
                self._state_of_id[s.id] = _GROUP_TO_STATE[s.group]

    def _check_config(self, features, types, states, labels) -> tuple[dict[Level, str], list[str]]:
        cfg = self.config
        problems: list[str] = []
        resolved: dict[Level, str] = {}
        type_names = ", ".join(t.name for t in types) or "(none)"
        self._level_of_type = {}
        self._level_of_label = {}
        for level, mapping in cfg.levels.items():
            how, ref = mapping.how, mapping.ref or ""
            if mapping.collapse is not None:
                try:
                    mapping.collapse.template.format(level="", name="", id="", key="")
                except (KeyError, IndexError, ValueError) as exc:
                    problems.append(
                        f"levels.{level.value}.template: only {{name}}, {{id}}, {{key}} and "
                        f"{{level}} are placeholders ({exc.__class__.__name__}: {exc})"
                    )
            if how is Materialization.TYPE:
                hit = next((t for t in types if ref in (t.id, t.name) or ref.lower() == t.name.lower()), None)
                if hit is None:
                    problems.append(f"levels.{level.value}: no work-item type {ref!r} on the board (types: {type_names})")
                else:
                    resolved[level] = hit.id
                    self._level_of_type[hit.id] = level
            elif how is Materialization.CONTAINER:
                if ref.lower() != "module":
                    problems.append(f"levels.{level.value}: Plane's only container is 'module', not {ref!r}")
                else:
                    resolved[level] = "module"
                    if isinstance(features, dict) and features.get("modules") is False:
                        problems.append(f"levels.{level.value}: the Modules feature is off on this project")
            elif how in (Materialization.PARENT, Materialization.LABEL):
                if ref.lower() not in self._labels:
                    problems.append(f"levels.{level.value}: no label {ref!r} on the board")
                else:
                    resolved[level] = self._labels[ref.lower()]
                    self._level_of_label[self._labels[ref.lower()]] = level
        if isinstance(features, dict) and features.get("cycles") is False:
            problems.append("the Cycles feature is off on this project (iterations need it)")

        state_names = ", ".join(s.name for s in states) or "(none)"
        self._state_id = {}
        for state, name in cfg.states.items():
            hit = next((s for s in states if s.name.lower() == name.lower()), None)
            if hit is None:
                problems.append(f"states.{state.value}: no state named {name!r} on the board (states: {state_names})")
            else:
                self._state_id[state] = hit.id
                self._state_of_id[hit.id] = state

        label_names = ", ".join(l.name for l in labels) or "(none)"
        if cfg.labels.review.lower() not in self._labels:
            problems.append(f"labels.review: no label {cfg.labels.review!r} on the board (labels: {label_names})")
        missing = [t for t in cfg.labels.taxonomy if t.lower() not in self._labels]
        if missing:
            problems.append(f"labels.taxonomy: not on the board: {', '.join(missing)}")
        return resolved, problems

    # -- resolvers ------------------------------------------------------------------

    def _item_id(self, ref: ItemRef | str) -> str:
        ident = ref.id if isinstance(ref, ItemRef) else ref
        if _UUID.match(ident):
            return ident
        return self.get_item(ident).id or ident

    def _label_id(self, name: str) -> str:
        hit = self._labels.get(name) or self._labels.get(name.lower())
        if hit is None:
            have = ", ".join(sorted(self._label_name.values())) or "(none)"
            raise ValidationError(f"no label {name!r} on the board (labels: {have})")
        return hit

    def _member_id(self, who: str) -> str:
        hit = self._members.get(who) or self._members.get(who.lower())
        if hit is None:
            have = ", ".join(sorted(self._member_name.values())) or "(none)"
            raise ValidationError(f"no member {who!r} in the workspace (members: {have})")
        return hit

    def _module_id(self, ref: ItemRef | str) -> str:
        ident = ref.id if isinstance(ref, ItemRef) else ref
        hit = self._modules.get(ident) or self._modules.get(ident.lower())
        if hit is None:
            raise ValidationError(f"no module {ident!r} on the board (feature / component must name an existing module)")
        return hit

    def _cycle_id(self, ident: str) -> str:
        hit = self._cycles.get(ident)
        if hit is None:  # maybe created since describe_board — re-read once
            for c in self._t.get_all(f"{self._pp}/cycles/"):
                self._cycles[c["id"]] = c["id"]
                self._cycles[c.get("name") or ""] = c["id"]
            hit = self._cycles.get(ident)
        if hit is None:
            raise NotFound(f"no iteration {ident!r} on the board")
        return hit

    # -- conversions ------------------------------------------------------------------

    def _to_item(self, rec: dict[str, Any]) -> WorkItem:
        type_id = _ref_id(rec.get("type_id") or rec.get("type"))
        # the list read carries ids; a single-item read, whole label objects
        label_ids = [i for i in map(_ref_id, rec.get("labels") or rec.get("label_ids") or []) if i]
        # a marker label (LABEL / PARENT materialization) outranks the type,
        # which is only the project default on such an item
        level = next((self._level_of_label[l] for l in label_ids if l in self._level_of_label), None)
        if level is None and type_id:
            level = self._level_of_type.get(type_id)
        if level is None:
            level = Level.EPIC if self._type_is_epic.get(type_id) else Level.STORY
        parent_id = _ref_id(rec.get("parent"))
        state_id = _ref_id(rec.get("state") or rec.get("state_id"))
        labels = tuple(self._label_name.get(l, l) for l in label_ids)
        assignees = tuple(
            self._member_name.get(a, a) for a in map(_ref_id, rec.get("assignees") or rec.get("assignee_ids") or []) if a
        )
        feature = None
        if self.config.levels[Level.FEATURE].how is Materialization.CONTAINER:
            mod = rec.get("min_module_name")
            if mod and mod.lower() in self._modules:
                feature = ItemRef(self._modules[mod.lower()], Level.FEATURE)
        key = None
        if rec.get("sequence_id") is not None and self.project.get("identifier"):
            key = f"{self.project['identifier']}-{rec['sequence_id']}"
        description = markdown.to_text(rec.get("description_html") or "") or (rec.get("description_stripped") or "")
        return WorkItem(
            level=level,
            title=rec.get("name") or "",
            description=description,
            id=rec.get("id"),
            key=key,
            parent=ItemRef(parent_id) if parent_id else None,
            feature=feature if level in (Level.STORY, Level.BUG) else None,
            state=self._state_of_id.get(state_id, State.BACKLOG) if state_id else State.BACKLOG,
            assignees=assignees,
            labels=labels,
            iteration=_ref_id(rec.get("cycle_id") or rec.get("cycle")),
            external_id=rec.get("external_id"),
        )

    def _module_as_item(self, rec: dict[str, Any]) -> WorkItem:
        return WorkItem(
            level=Level.FEATURE,
            title=rec.get("name") or "",
            description=rec.get("description") or "",
            id=rec.get("id"),
        )

    def _cycle_date(self, value: Any) -> date | None:
        """Plane keeps a cycle's dates as datetimes on the project timezone's
        day edges (start 00:00:01, end 23:59) but renders them at another
        offset: `2026-10-01` reads back as `2026-09-30T20:00:01-04:00`. The
        project's zone recovers the calendar day (conformance, 2026-09-22)."""
        moment = _datetime(value)
        if moment is None or moment.tzinfo is None:
            return _date(value)
        return moment.astimezone(self._zone).date()

    @property
    def _zone(self) -> tzinfo:
        try:
            return ZoneInfo(self.project.get("timezone") or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            return timezone.utc

    def _to_iteration(self, rec: dict[str, Any]) -> Iteration:
        start = self._cycle_date(rec.get("start_date"))
        end = self._cycle_date(rec.get("end_date"))
        status = (rec.get("status") or "").lower()
        if status in _CYCLE_STATUS:
            state = _CYCLE_STATUS[status]
        elif status:
            state = IterationState.PLANNED
        else:
            today = self._today()
            if end and end < today:
                state = IterationState.CLOSED
            elif start and start <= today and (end is None or end >= today):
                state = IterationState.ACTIVE
            else:
                state = IterationState.PLANNED
        return Iteration(rec.get("name") or "", id=rec.get("id"), start=start, end=end, state=state)

    def _collapse(self, level: Level, ref: ItemRef) -> tuple[list[str], list[str], list[str]]:
        """Apply the collapse rule for an attachment of `level`; returns
        (labels, modules, description lines) to add."""
        rule: CollapseRule | None = self.config.levels[level].collapse
        if rule is None:
            raise Unsupported(
                f"a {level.value} attachment has no realization on this board "
                f"(levels.{level.value} is neither a container nor collapsed)"
            )
        text = rule.template.format(level=level.value, name=ref.key or ref.id, id=ref.id, key=ref.key or "")
        if rule.target is CollapseTarget.LABEL:
            return [text], [], []
        if rule.target is CollapseTarget.COMPONENT:
            return [], [text], []
        return [], [], [text]

    # -- read ----------------------------------------------------------------------------

    def get_item(self, ref: ItemRef | str) -> WorkItem:
        self._ready_maps()
        ident = ref.id if isinstance(ref, ItemRef) else ref
        if _UUID.match(ident):
            rec = self._t.request("GET", f"{self._pp}/work-items/{ident}/")
        else:  # a human key like AA-12 — retrieve by identifier
            rec = self._t.request("GET", f"{self._ws}/work-items/{ident}/")
        if not isinstance(rec, dict) or not rec.get("id"):
            raise NotFound(f"work item {ident!r} not found")
        return self._to_item(rec)

    def get_iteration(self, iteration: str) -> Iteration:
        cycle_id = self._cycle_id(iteration)
        return self._to_iteration(self._t.request("GET", f"{self._pp}/cycles/{cycle_id}/"))

    def find_items(self, query: str = "", *, external_id=None, level=None, state=None, iteration=None,
                   label=None, limit=50) -> list[WorkItem]:
        self._ready_maps()
        cycle_id = self._cycle_id(iteration) if iteration else None
        # modules and initiatives are never in a cycle: with one, fall through to an empty item read
        if level is Level.FEATURE and self.config.levels[Level.FEATURE].how is Materialization.CONTAINER \
                and cycle_id is None:
            mods = [self._module_as_item(m) for m in self._t.get_all(f"{self._pp}/modules/")]
            return [m for m in mods if query.lower() in m.title.lower()][:limit]
        if level is Level.INITIATIVE and cycle_id is None:
            inits = self._t.get_all(f"{self._ws}/initiatives/")
            return [
                WorkItem(Level.INITIATIVE, i.get("name") or "", i.get("description") or "", id=i.get("id"))
                for i in inits if query.lower() in (i.get("name") or "").lower()
            ][:limit]

        if external_id:
            # the project list with both params is Plane's idempotency lookup:
            # one record, or 404 (the workspace search ignores them)
            params = {"external_id": external_id, "external_source": self.EXTERNAL_SOURCE}
            try:
                rec = self._t.request("GET", f"{self._pp}/work-items/", params=params)
            except NotFound:
                rec = None
            if isinstance(rec, dict) and "results" in rec:
                raise TransportError(
                    "Plane ignored the external_id filter and answered with the item list; "
                    "refusing to guess, so no create can duplicate an item"
                )
            items = [self._to_item(rec)] if isinstance(rec, dict) and rec.get("id") else []
            items = [i for i in items if i.external_id == external_id and query.lower() in i.title.lower()]
        elif cycle_id:
            # the cycle's membership read: full item records (AOR tools/plane/API.md), a completed cycle's too
            rows = self._t.get_all(f"{self._pp}/cycles/{cycle_id}/cycle-issues/")
            items = [replace(self._to_item(r), iteration=cycle_id) for r in rows]
            items = [i for i in items if query.lower() in i.title.lower()]
        elif query:
            hits = self._t.request("GET", f"{self._ws}/work-items/search/", params={"search": query})
            rows = hits.get("issues") or hits.get("results") or [] if isinstance(hits, dict) else (hits or [])
            pid = self.project["id"]
            items = []
            for r in rows:
                proj = r.get("project_id") or r.get("project")
                if proj and proj != pid:
                    continue
                try:
                    items.append(self.get_item(r["id"]))
                except NotFound:
                    continue
                if len(items) >= limit * 2:  # keep the hydration bounded
                    break
        else:
            items = [self._to_item(r) for r in self._t.get_all(f"{self._pp}/work-items/")]
        if level is not None:
            items = [i for i in items if i.level is level]
        if state is not None:
            items = [i for i in items if i.state is state]
        if cycle_id:
            items = [i for i in items if i.iteration == cycle_id]
        if label:  # label names match as the config's do: ignoring case
            items = [i for i in items if label.lower() in {name.lower() for name in i.labels}]
        return items[:limit]

    def _ready_maps(self) -> None:
        """Reads need the lookup tables but not a clean config."""
        if self._board is None:
            self.describe_board()

    # -- write ---------------------------------------------------------------------------

    def create_item(self, item: WorkItem) -> WorkItem:
        item.check()
        board = self._ready()
        level, mapping = item.level, self.config.levels[item.level]

        if level is Level.INITIATIVE:
            raise Unsupported("Plane initiatives are read-only in v1 (they sit above projects)")
        if level is Level.FEATURE and mapping.how is Materialization.CONTAINER:
            if item.parent is not None:
                raise Unsupported("a Plane module has no parent; a feature's epic is carried by its stories")
            body = {"name": item.title, "project_id": board.project_id}
            if item.description:
                body["description"] = item.description
            rec = self._t.request("POST", f"{self._pp}/modules/", body=body)
            self._modules[rec["id"]] = rec["id"]
            self._modules[(rec.get("name") or item.title).lower()] = rec["id"]
            return self._module_as_item(rec)
        if mapping.how is Materialization.NONE:
            raise Unsupported(f"levels.{level.value} collapses on this board; nothing to create")

        labels = list(item.labels)
        modules: list[ItemRef | str] = []
        lines: list[str] = []
        if item.initiative is not None:
            more_labels, more_modules, more_lines = self._collapse(Level.INITIATIVE, item.initiative)
            labels += more_labels
            modules += more_modules
            lines += more_lines
        if item.feature is not None:
            if self.config.levels[Level.FEATURE].how is Materialization.CONTAINER:
                modules.append(item.feature)
            else:
                more_labels, more_modules, more_lines = self._collapse(Level.FEATURE, item.feature)
                labels += more_labels
                modules += more_modules
                lines += more_lines
        if item.component:
            modules.append(item.component)
        if mapping.how in (Materialization.PARENT, Materialization.LABEL):
            labels.append(mapping.ref or "")

        body: dict[str, Any] = {"name": item.title, "state": self._state_id[item.state]}
        if mapping.how is Materialization.TYPE:
            body["type_id"] = board.resolved[level]
        if item.parent is not None:
            body["parent"] = self._item_id(item.parent)
        description = "\n".join(lines + ([item.description] if item.description else []))
        if description:
            body["description_html"] = markdown.render(description)
        if labels:
            body["labels"] = _dedupe(self._label_id(l) for l in labels)
        if item.assignees:
            body["assignees"] = _dedupe(self._member_id(a) for a in item.assignees)
        if item.external_id:
            body["external_id"] = item.external_id
            body["external_source"] = self.EXTERNAL_SOURCE
        module_ids = _dedupe(self._module_id(m) for m in modules)  # resolve before the POST
        cycle_id = self._cycle_id(item.iteration) if item.iteration else None

        rec = self._t.request("POST", f"{self._pp}/work-items/", body=body)
        created = self._to_item(rec)
        for mid in module_ids:
            self._t.request("POST", f"{self._pp}/modules/{mid}/module-issues/", body={"issues": [created.id]})
        if cycle_id:
            self._t.request("POST", f"{self._pp}/cycles/{cycle_id}/cycle-issues/", body={"issues": [created.id]})
        return replace(
            created,
            feature=item.feature if module_ids and item.feature is not None else created.feature,
            component=item.component,
            iteration=cycle_id or created.iteration,
            initiative=item.initiative,
        )

    def update_item(self, ref: ItemRef | str, patch: ItemPatch) -> WorkItem:
        if patch.is_empty():
            raise ValidationError("nothing to update: the patch is empty")
        self._ready()
        item_id = self._item_id(ref)
        body: dict[str, Any] = {}
        if patch.title is not None:
            body["name"] = patch.title
        if patch.description is not None:
            body["description_html"] = markdown.render(patch.description)
        if patch.state is not None:
            body["state"] = self._state_id[patch.state]
        if patch.assignees is not None:
            body["assignees"] = _dedupe(self._member_id(a) for a in patch.assignees)
        if patch.labels is not None:
            wanted = [self._label_id(l) for l in patch.labels]
            if self._level_of_label:  # keep a marker label: labels never change an item's level
                current = self.get_item(item_id)
                marker = self.config.levels[current.level].ref or ""
                if self.config.levels[current.level].how in (Materialization.LABEL, Materialization.PARENT):
                    wanted.append(self._label_id(marker))
            body["labels"] = _dedupe(wanted)
        if patch.parent is not None:
            body["parent"] = self._item_id(patch.parent)
        module_id = None
        if patch.feature is not None:
            if self.config.levels[Level.FEATURE].how is not Materialization.CONTAINER:
                raise Unsupported("feature is not a container on this board; set it at creation via the collapse rule")
            module_id = self._module_id(patch.feature)
        if body:
            rec = self._t.request("PATCH", f"{self._pp}/work-items/{item_id}/", body=body)
        else:
            rec = self._t.request("GET", f"{self._pp}/work-items/{item_id}/")
        if module_id:  # membership is additive — no DELETE, ever
            self._t.request("POST", f"{self._pp}/modules/{module_id}/module-issues/", body={"issues": [item_id]})
        updated = self._to_item(rec)
        return replace(updated, feature=patch.feature) if module_id else updated

    def add_comment(self, comment: Comment) -> Comment:
        self._ready()
        item_id = self._item_id(comment.item)
        rec = self._t.request(
            "POST", f"{self._pp}/work-items/{item_id}/comments/",
            body={"comment_html": markdown.render(comment.body)},
        )
        actor = rec.get("actor") if isinstance(rec, dict) else None
        return replace(
            comment,
            id=rec.get("id") if isinstance(rec, dict) else None,
            author=self._member_name.get(actor, actor) if isinstance(actor, str) else None,
            created_at=_datetime(rec.get("created_at")) if isinstance(rec, dict) else None,
        )

    def create_iteration(self, iteration: Iteration) -> Iteration:
        board = self._ready()
        if not self.config.naming.iteration_name_ok(iteration.name):
            raise ValidationError(
                f"iteration name {iteration.name!r} does not match naming.iteration "
                f"{self.config.naming.iteration!r}"
            )
        # find-or-create by name; a cycle is active by its dates, so nothing to start
        found = next((c for c in self._t.get_all(f"{self._pp}/cycles/") if c.get("name") == iteration.name), None)
        if found is not None:
            return existing_iteration(self._to_iteration(found), iteration)
        body: dict[str, Any] = {"name": iteration.name, "project_id": board.project_id}
        if iteration.start:
            body["start_date"] = iteration.start.isoformat()
        if iteration.end:
            body["end_date"] = iteration.end.isoformat()
        rec = self._t.request("POST", f"{self._pp}/cycles/", body=body)
        self._cycles[rec["id"]] = rec["id"]
        self._cycles[rec.get("name") or iteration.name] = rec["id"]
        return self._to_iteration(rec)

    def move_to_iteration(self, items: Sequence[ItemRef | str], iteration: str) -> None:
        self._ready()
        cycle_id = self._cycle_id(iteration)
        ids = _dedupe(self._item_id(i) for i in items)
        if not ids:
            return
        self._t.request("POST", f"{self._pp}/cycles/{cycle_id}/cycle-issues/", body={"issues": ids})

    def close_iteration(self, iteration: str) -> Iteration:
        self._ready()
        current = self.get_iteration(iteration)
        if current.state is IterationState.CLOSED:
            return current
        today = self._today()
        if current.start and current.start >= today:
            when = "has not started" if current.start > today else "started today"
            raise ValidationError(
                f"iteration {current.name!r} {when}; Plane completes a cycle only once its "
                "end date has passed, so it can be closed from tomorrow"
            )
        # Plane completes a cycle once end_date < today (one ending today is
        # still current — conformance, 2026-09-22): pull the end to yesterday.
        end = today - timedelta(days=1)
        self._t.request("PATCH", f"{self._pp}/cycles/{current.id}/", body={"end_date": end.isoformat()})
        closed = self.get_iteration(current.id or iteration)
        if closed.state is not IterationState.CLOSED:
            raise ValidationError(
                f"iteration {current.name!r} did not close: Plane still reports it "
                f"{closed.state.value} after end_date was set to {end.isoformat()}"
            )
        return closed

    # -- Plane-specific extras (not on the interface) ------------------------------------

    def set_features(self, **flags: bool) -> dict[str, Any]:
        """PATCH the project's feature flags (`work_item_types`, `epics`,
        `modules`, `cycles`, …) and return what a fresh read reports. The
        route is the SDK's; whether it flips `epics` (API.md: UI-only) is a
        conformance case, so callers check the re-read, not the PATCH."""
        self._t.request("PATCH", f"{self._pp}/features/", body=flags)
        self._board = None
        after = self._t.request("GET", f"{self._pp}/features/")
        return dict(after) if isinstance(after, dict) else {}

    def provision(self, *, types: Sequence[str] = (), labels: Sequence[str] = ()) -> BoardDescription:
        """Create whichever of these non-epic work-item types and labels the
        board lacks (idempotent by name), then re-read the board. An epic
        type cannot be made here: Plane ignores `is_epic` on create, and the
        type appears only once the project's Epics feature is on."""
        board = self._board or self.describe_board()
        have_types = {t.name.lower() for t in board.types}
        have_labels = {l.name.lower() for l in board.labels}
        missing = [("work-item-types/", n) for n in types if n.lower() not in have_types]
        missing += [("labels/", n) for n in labels if n.lower() not in have_labels]
        if not missing:
            return board
        self._board = None  # stale from the first write on, even if a later one fails
        made: set[tuple[str, str]] = set()
        for route, name in missing:
            if (route, name.lower()) not in made:
                self._t.request("POST", f"{self._pp}/{route}", body={"name": name})
                made.add((route, name.lower()))
        return self.describe_board()

    def provision_work_item_type(self, name: str) -> TypeInfo:
        """Create a non-epic work-item type (the Phase 1 finding: no board
        ships a Bug type). Idempotent by name."""
        board = self.provision(types=[name])
        hit = next((t for t in board.types if t.name.lower() == name.lower()), None)
        if hit is None:
            raise ValidationError(f"created work-item type {name!r} but the board does not list it")
        return hit


# --- helpers ---------------------------------------------------------------------------


def _ref_id(value: Any) -> str | None:
    """Plane returns related objects as an id, or as `{id, ...}` when expanded."""
    if isinstance(value, dict):
        return value.get("id")
    return value or None


def _dedupe(values) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        seen.setdefault(v, None)
    return list(seen)


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
