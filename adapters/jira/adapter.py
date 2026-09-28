"""The Jira Cloud adapter (design: roadmap/14 §4 D2, §5; live findings from
the Phase 5 probe, probes/README.md 2026-09-27).

How the canonical model lands on a company-managed Jira project:

- Epic / Story / Bug / Task are **issue types**, named per level in the
  board config. Jira fixes their hierarchy levels: Epic 1, Story and Bug 0,
  and the canonical Task, a story's child, is a **sub-task** (−1).
  `describe_board` reports a config whose types sit at the wrong level.
  The parent chain is the issue's `parent` field at every level.
- Initiative and Feature **collapse** (Chris, 2026-09-27). Premium's custom
  levels sit only above Epic, so a Feature cannot sit between Epic and
  Story. A collapse rule's label has its spaces turned into dashes: Jira
  labels cannot hold whitespace.
- `component` is a Jira **component** (it must exist).
- States are workflow **statuses**, named in the config. A status changes
  through the issue's transition whose target is that status. A new issue
  starts at the workflow's initial status and moves on in a second step.
- Jira has no `external_id`: the idempotency key is the label
  `xid:<external_id>`, set in the create call and found with JQL
  `labels = "…"` (the only exact text match JQL has). The label is kept
  whenever labels are replaced, and hidden from `WorkItem.labels`.
  `/search/jql` is eventually consistent, so this process also remembers
  the issues it created and reads them directly.
- Labels are free-form: one exists once an issue carries it. The board's
  label set is therefore the site's labels plus the config's review and
  taxonomy labels, so a board with no issues yet still fits.
- Iterations are **sprints** on the config's Scrum board. Dates decide
  (Chris, 2026-09-27): `create_iteration` starts a sprint whose dates
  cover today. It is find-or-create by name (Phase 6), so it also starts
  a sprint created ahead of time once its first day comes. Sprint dates
  are written on the account time zone's day edges and read back in it.
- `find_items(iteration=…)` is JQL `sprint = <id>`, which also matches
  the closed sprints in an issue's Sprint field; the adapter keeps the
  issues whose current sprint it is.
- Descriptions and comments are Markdown in, ADF out (`adapters.jira.adf`).

No delete: there is no DELETE request in this file.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime, time, timezone, tzinfo
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from adapters.base import (
    Adapter,
    BoardDescription,
    ItemPatch,
    NamedRef,
    NotFound,
    StateInfo,
    TypeInfo,
    Unsupported,
    ValidationError,
    existing_iteration,
)
from adapters.jira import adf
from adapters.jira.transport import JiraTransport, Transport
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

XID = "xid:"
SPRINT_FIELD = "com.pyxis.greenhopper.jira:gh-sprint"
# The hierarchy level each core level's issue type must sit at.
_WANT_LEVEL = {Level.EPIC: 1, Level.STORY: 0, Level.BUG: 0, Level.TASK: -1}
# Status categories line up with the canonical states for a status the config did not name.
_CATEGORY_TO_STATE = {"new": State.BACKLOG, "indeterminate": State.IN_PROGRESS, "done": State.DONE}
_SPRINT_STATE = {"future": IterationState.PLANNED, "active": IterationState.ACTIVE, "closed": IterationState.CLOSED}
# Lucene's reserved characters, dropped from a free-text query rather than escaped
_TEXT_RESERVED = re.compile(r'[+\-&|!(){}\[\]^~*?\\:"/]')
_MOVE_BATCH = 50  # issues per POST …/sprint/{id}/issue
_SPRINT_SCAN = 1000  # rows read for find_items(iteration=…) before the current-sprint filter


class JiraAdapter(Adapter):
    backend = "jira"

    def __init__(
        self,
        config: BoardConfig,
        transport: Transport | None = None,
        *,
        secret: Callable[[str], str] = secrets.get,
        today: Callable[[], date] = date.today,
    ) -> None:
        if config.backend is not Backend.JIRA:
            raise ValueError(f"JiraAdapter got a {config.backend.value} config")
        super().__init__(config)
        conn = config.connection
        self.project_key = conn.ids["project_key"]
        self.board_id = conn.ids["board_id"]
        user_env = conn.user_env or ""
        self._t: Transport = transport or JiraTransport(
            conn.base_url or conn.ids["site"], lambda: secret(user_env), lambda: secret(conn.token_env)
        )
        self._today = today
        self._caps = Capabilities(
            self.backend,
            config.materializations(),
            DescriptionFormat.ADF,
            states_via_transitions=True,
            native_idempotency_key=False,
            collapse=config.collapse_rules(),
        )
        self._board: BoardDescription | None = None
        # lookup tables filled by describe_board
        self._level_of_type: dict[str, Level] = {}
        self._hierarchy_of_type: dict[str, int] = {}
        self._level_of_label: dict[str, Level] = {}  # lower marker label -> LABEL/PARENT level
        self._state_id: dict[State, str] = {}
        self._state_of_id: dict[str, State] = {}
        self._members: dict[str, str] = {}  # lower name / email / accountId -> accountId
        self._member_name: dict[str, str] = {}
        self._components: dict[str, str] = {}  # lower name / id -> id
        self._sprints: dict[str, str] = {}  # name / id -> id
        self._sprint_field: str | None = None
        self._zone: tzinfo = timezone.utc
        self._created: dict[str, str] = {}  # external_id -> issue id, created by this process

    # -- plumbing ------------------------------------------------------------------

    @property
    def capabilities(self) -> Capabilities:
        return self._caps

    def _ready(self) -> BoardDescription:
        """The write gate: the cached board description, clean."""
        if self._board is None:
            self.describe_board()
        assert self._board is not None
        return self._board.check()

    def _ready_maps(self) -> None:
        """Reads need the lookup tables but not a clean config."""
        if self._board is None:
            self.describe_board()

    # -- describe ------------------------------------------------------------------

    def describe_board(self) -> BoardDescription:
        key = self.project_key
        proj = self._t.request("GET", f"/rest/api/3/project/{key}", params={"expand": "issueTypes"})
        issue_types = proj.get("issueTypes") or []
        types = [TypeInfo(str(t["id"]), t.get("name") or "", t.get("hierarchyLevel") == 1) for t in issue_types]
        self._hierarchy_of_type = {str(t["id"]): int(t.get("hierarchyLevel") or 0) for t in issue_types}
        by_id: dict[str, StateInfo] = {}
        for per_type in self._t.request("GET", f"/rest/api/3/project/{key}/statuses") or []:
            for s in per_type.get("statuses") or []:
                by_id.setdefault(str(s["id"]), StateInfo(str(s["id"]), s.get("name") or "",
                                                         (s.get("statusCategory") or {}).get("key")))
        states = list(by_id.values())
        site_labels = [l for l in self._t.get_all("/rest/api/3/label") if isinstance(l, str) and not l.startswith(XID)]
        members = [
            NamedRef(u["accountId"], u.get("displayName") or u["accountId"], {"email": u.get("emailAddress")})
            for u in self._t.get_all("/rest/api/3/user/assignable/search", {"project": key, "maxResults": 1000})
            if u.get("accountType") == "atlassian"
        ]
        components = [NamedRef(str(c["id"]), c.get("name") or "")
                      for c in self._t.request("GET", f"/rest/api/3/project/{key}/components") or []]
        fields = self._t.request("GET", "/rest/api/3/field") or []
        self._sprint_field = next((f["id"] for f in fields if (f.get("schema") or {}).get("custom") == SPRINT_FIELD), None)
        me = self._t.request("GET", "/rest/api/3/myself") or {}
        self._zone = _zone(me.get("timeZone"))
        board = self._t.request("GET", f"/rest/agile/1.0/board/{self.board_id}") or {}
        sprints = self._t.get_all(f"/rest/agile/1.0/board/{self.board_id}/sprint") if board.get("type") == "scrum" else []
        iterations = [
            NamedRef(str(s["id"]), s.get("name") or "",
                     {"state": s.get("state"), "start": s.get("startDate"), "end": s.get("endDate")})
            for s in sprints
        ]

        cfg = self.config
        declared = [cfg.labels.review, *cfg.labels.taxonomy]
        labels = [NamedRef(l, l) for l in _dedupe([*site_labels, *declared])]
        self._index(members, components, iterations, states)
        resolved, problems = self._check_config(types, states, declared)
        if board.get("type") != "scrum":
            problems.append(f"board {self.board_id} is a {board.get('type')!r} board; sprints need a scrum board")
        board_project = (board.get("location") or {}).get("projectKey")
        if board_project and board_project != proj.get("key"):
            problems.append(f"board {self.board_id} belongs to project {board_project}, not {proj.get('key')}")
        if self._sprint_field is None:
            problems.append("no Sprint field on the site (is Jira Software on?)")
        self._board = BoardDescription(
            backend=self.backend,
            project_id=str(proj["id"]),
            project_key=proj.get("key"),
            project_name=proj.get("name"),
            features={"style": proj.get("style"), "simplified": proj.get("simplified"),
                      "board_type": board.get("type"), "sprint_field": self._sprint_field,
                      "time_zone": me.get("timeZone")},
            types=tuple(types),
            states=tuple(states),
            labels=tuple(labels),
            members=tuple(members),
            containers=tuple(components),
            iterations=tuple(iterations),
            resolved=resolved,
            problems=tuple(problems),
        )
        return self._board

    def _index(self, members, components, iterations, states) -> None:
        self._members, self._member_name = {}, {}
        for m in members:
            self._members[m.id] = m.id
            self._members[m.name.lower()] = m.id
            if m.extra.get("email"):
                self._members[str(m.extra["email"]).lower()] = m.id
            self._member_name[m.id] = m.name
        self._components = {}
        for c in components:
            self._components[c.id] = c.id
            self._components[c.name.lower()] = c.id
        self._sprints = {}
        for s in iterations:
            self._sprints[s.id] = s.id
            self._sprints[s.name] = s.id
        # status ids: the config's names first, then the category as the read fallback
        self._state_of_id = {s.id: _CATEGORY_TO_STATE[s.group] for s in states if s.group in _CATEGORY_TO_STATE}

    def _check_config(self, types, states, declared) -> tuple[dict[Level, str], list[str]]:
        cfg = self.config
        problems: list[str] = []
        resolved: dict[Level, str] = {}
        type_names = ", ".join(t.name for t in types) or "(none)"
        self._level_of_type, self._level_of_label = {}, {}
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
                hit = next((t for t in types if ref == t.id or ref.lower() == t.name.lower()), None)
                if hit is None:
                    problems.append(f"levels.{level.value}: no issue type {ref!r} in the project (types: {type_names})")
                    continue
                have = self._hierarchy_of_type.get(hit.id, 0)
                want = _WANT_LEVEL.get(level)
                if level is Level.FEATURE:
                    problems.append("levels.feature: Jira has no hierarchy level between Epic and Story; collapse it")
                elif level is Level.INITIATIVE and have < 2:
                    problems.append(f"levels.initiative: issue type {hit.name!r} is at hierarchy level {have}; "
                                    "an initiative needs a Premium level above Epic (2+), or collapse it")
                elif want is not None and have != want:
                    hint = " (a sub-task type)" if level is Level.TASK else ""
                    problems.append(f"levels.{level.value}: issue type {hit.name!r} is at hierarchy level {have}; "
                                    f"a {level.value} needs level {want}{hint}")
                else:
                    resolved[level] = hit.id
                    self._level_of_type[hit.id] = level
            elif how is Materialization.CONTAINER:
                problems.append(f"levels.{level.value}: Jira has no container level; collapse it "
                                "(label, component or description_line)")
            elif how in (Materialization.PARENT, Materialization.LABEL):
                if not _label_ok(ref):
                    problems.append(f"levels.{level.value}: {ref!r} is not a valid Jira label (no spaces)")
                else:
                    resolved[level] = ref
                    self._level_of_label[ref.lower()] = level

        state_names = ", ".join(s.name for s in states) or "(none)"
        self._state_id = {}
        for state, name in cfg.states.items():
            hit = next((s for s in states if s.name.lower() == name.lower()), None)
            if hit is None:
                problems.append(f"states.{state.value}: no status named {name!r} in the project (statuses: {state_names})")
            else:
                self._state_id[state] = hit.id
                self._state_of_id[hit.id] = state

        bad = [l for l in declared if not _label_ok(l)]
        if bad:
            problems.append(f"labels: Jira labels cannot contain spaces: {', '.join(repr(l) for l in bad)}")
        return resolved, problems

    # -- resolvers -----------------------------------------------------------------

    @staticmethod
    def _ident(ref: ItemRef | str) -> str:
        if isinstance(ref, ItemRef):
            return ref.key or ref.id
        return ref

    def _parent_field(self, ref: ItemRef | str) -> dict[str, str]:
        ident = self._ident(ref)
        return {"id": ident} if ident.isdigit() else {"key": ident}

    def _member_id(self, who: str) -> str:
        hit = self._members.get(who) or self._members.get(who.lower())
        if hit is None:
            have = ", ".join(sorted(self._member_name.values())) or "(none)"
            raise ValidationError(f"no assignable user {who!r} in the project (users: {have})")
        return hit

    def _component_id(self, name: str) -> str:
        hit = self._components.get(name) or self._components.get(name.lower())
        if hit is None:
            have = ", ".join(sorted(n for n in self._components if not n.isdigit())) or "(none)"
            raise ValidationError(f"no component {name!r} in the project (components: {have})")
        return hit

    def _sprint_id(self, ident: str) -> str:
        hit = self._sprints.get(ident)
        if hit is None:  # maybe created since describe_board — re-read once
            for s in self._t.get_all(f"/rest/agile/1.0/board/{self.board_id}/sprint"):
                self._sprints[str(s["id"])] = str(s["id"])
                self._sprints[s.get("name") or ""] = str(s["id"])
            hit = self._sprints.get(ident)
        if hit is None and ident.isdigit():
            return ident  # a sprint id off this board's list: let the read answer
        if hit is None:
            raise NotFound(f"no sprint {ident!r} on board {self.board_id}")
        return hit

    def _labels_for_write(self, labels: Sequence[str]) -> list[str]:
        for l in labels:
            if not _label_ok(l):
                raise ValidationError(f"{l!r} is not a valid Jira label (no spaces, at most 255 characters)")
        return _dedupe(labels)

    # -- conversions ---------------------------------------------------------------

    def _fields(self) -> list[str]:
        base = ["summary", "description", "issuetype", "parent", "status", "labels", "assignee", "components", "created"]
        return base + ([self._sprint_field] if self._sprint_field else [])

    def _level_of(self, issuetype: dict[str, Any], labels: Sequence[str] = ()) -> Level:
        # a marker label (LABEL / PARENT materialization) outranks the type
        level = next((self._level_of_label[l.lower()] for l in labels if l.lower() in self._level_of_label), None)
        if level is not None:
            return level
        tid = str(issuetype.get("id") or "")
        if tid in self._level_of_type:
            return self._level_of_type[tid]
        h = issuetype.get("hierarchyLevel", self._hierarchy_of_type.get(tid, 0))
        return Level.EPIC if h == 1 else Level.TASK if h == -1 or issuetype.get("subtask") else Level.STORY

    def _to_item(self, rec: dict[str, Any]) -> WorkItem:
        f = rec.get("fields") or {}
        all_labels = [l for l in f.get("labels") or [] if isinstance(l, str)]
        xid = next((l[len(XID):] for l in all_labels if l.startswith(XID)), None)
        labels = tuple(l for l in all_labels if not l.startswith(XID))
        parent = None
        if f.get("parent"):
            p = f["parent"]
            ptype = (p.get("fields") or {}).get("issuetype") or {}
            parent = ItemRef(str(p["id"]), self._level_of(ptype) if ptype else None, p.get("key"))
        status_id = str((f.get("status") or {}).get("id") or "")
        category = ((f.get("status") or {}).get("statusCategory") or {}).get("key")
        state = self._state_of_id.get(status_id) or _CATEGORY_TO_STATE.get(category, State.BACKLOG)
        assignee = f.get("assignee") or {}
        components = f.get("components") or []
        return WorkItem(
            level=self._level_of(f.get("issuetype") or {}, labels),
            title=f.get("summary") or "",
            description=adf.to_markdown(f.get("description")),
            id=str(rec.get("id")) if rec.get("id") is not None else None,
            key=rec.get("key"),
            parent=parent,
            state=state,
            assignees=(assignee.get("displayName") or assignee.get("accountId"),) if assignee else (),
            labels=labels,
            iteration=_current_sprint(f.get(self._sprint_field) if self._sprint_field else None),
            component=components[0].get("name") if components else None,
            external_id=xid,
        )

    def _day(self, value: Any) -> date | None:
        """Jira keeps sprint dates as instants; the account's zone recovers the day."""
        if not value:
            return None
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return moment.astimezone(self._zone).date() if moment.tzinfo else moment.date()

    def _edge(self, day: date, clock: time) -> str:
        return datetime.combine(day, clock, tzinfo=self._zone).isoformat(timespec="milliseconds")

    def _to_iteration(self, rec: dict[str, Any]) -> Iteration:
        return Iteration(
            rec.get("name") or "",
            id=str(rec["id"]) if rec.get("id") is not None else None,
            start=self._day(rec.get("startDate")),
            end=self._day(rec.get("endDate")),
            state=_SPRINT_STATE.get(rec.get("state") or "", IterationState.PLANNED),
        )

    def _collapse(self, level: Level, ref: ItemRef) -> tuple[list[str], list[str], list[str]]:
        """Apply the collapse rule for an attachment of `level`; returns
        (labels, components, description lines) to add."""
        rule: CollapseRule | None = self.config.levels[level].collapse
        if rule is None:
            raise Unsupported(f"a {level.value} attachment has no realization on this board "
                              f"(levels.{level.value} is not collapsed)")
        text = rule.template.format(level=level.value, name=ref.key or ref.id, id=ref.id, key=ref.key or "")
        if rule.target is CollapseTarget.LABEL:
            return [re.sub(r"\s+", "-", text.strip())], [], []
        if rule.target is CollapseTarget.COMPONENT:
            return [], [text], []
        return [], [], [text]

    # -- read ----------------------------------------------------------------------

    def get_item(self, ref: ItemRef | str) -> WorkItem:
        self._ready_maps()
        ident = self._ident(ref)
        rec = self._t.request("GET", f"/rest/api/3/issue/{ident}", params={"fields": ",".join(self._fields())})
        if not isinstance(rec, dict) or not rec.get("id"):
            raise NotFound(f"issue {ident!r} not found")
        return self._to_item(rec)

    def get_iteration(self, iteration: str) -> Iteration:
        self._ready_maps()
        return self._to_iteration(self._t.request("GET", f"/rest/agile/1.0/sprint/{self._sprint_id(iteration)}"))

    def _search(self, jql: str, limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        token: str | None = None
        while len(out) < limit:
            params = {"jql": jql, "fields": ",".join(self._fields()), "maxResults": min(100, limit - len(out)),
                      "nextPageToken": token}
            page = self._t.request("GET", "/rest/api/3/search/jql", params=params) or {}
            out += page.get("issues") or []
            token = page.get("nextPageToken")
            if page.get("isLast", True) or not token:
                break
        return out

    def find_items(self, query: str = "", *, external_id=None, level=None, state=None, iteration=None,
                   label=None, limit=50) -> list[WorkItem]:
        self._ready_maps()
        if level is not None and not self._caps.materializes(level):
            return []  # a collapsed level has no items of its own
        sprint_id = self._sprint_id(iteration) if iteration else None
        if sprint_id and sprint_id not in self._sprints:  # off this board's list: JQL would 400 on a missing one
            self._t.request("GET", f"/rest/agile/1.0/sprint/{sprint_id}")  # 404 → NotFound
        clauses = [f'project = "{_jql(self.project_key)}"']
        if sprint_id:
            clauses.append(f"sprint = {sprint_id}")
        if external_id:
            clauses.append(f'labels = "{_jql(XID + external_id)}"')
        if label:
            clauses.append(f'labels = "{_jql(label)}"')
        if query:
            clauses.append(f'text ~ "{_jql(_TEXT_RESERVED.sub(" ", query).strip())}"')
        if level is not None:
            mapping = self.config.levels[level]
            if mapping.how is Materialization.TYPE and level in self._board.resolved:  # type: ignore[union-attr]
                clauses.append(f"issuetype = {self._board.resolved[level]}")  # type: ignore[union-attr]
            elif mapping.how in (Materialization.PARENT, Materialization.LABEL):
                clauses.append(f'labels = "{_jql(mapping.ref or "")}"')
        if state is not None and state in self._state_id:
            clauses.append(f"status = {self._state_id[state]}")
        # `sprint =` overmatches (history), so scan wider; the filter below trims to the sprint's own
        scan = max(limit, _SPRINT_SCAN) if sprint_id else limit
        items = [self._to_item(r) for r in self._search(" AND ".join(clauses) + " ORDER BY created DESC", scan)]
        if external_id:
            known = self._created.get(external_id)
            if known and all(i.id != known for i in items):  # the search has not caught up yet
                try:
                    items.append(self.get_item(known))
                except NotFound:
                    pass
            items = [i for i in items if i.external_id == external_id]
        if level is not None:
            items = [i for i in items if i.level is level]
        if state is not None:
            items = [i for i in items if i.state is state]
        if label:  # the lagging-search item above came back unfiltered; case as the JQL decided
            items = [i for i in items if label.lower() in {name.lower() for name in i.labels}]
        if sprint_id:  # `sprint =` also matches the closed sprints in an issue's history
            items = [i for i in items if i.iteration == sprint_id]
        return items[:limit]

    # -- write ---------------------------------------------------------------------

    def create_item(self, item: WorkItem) -> WorkItem:
        item.check()
        board = self._ready()
        level, mapping = item.level, self.config.levels[item.level]
        if mapping.how is Materialization.NONE:
            raise Unsupported(f"levels.{level.value} collapses on this board; nothing to create")

        labels = list(item.labels)
        components: list[str] = [item.component] if item.component else []
        lines: list[str] = []
        for attached, ref in ((Level.INITIATIVE, item.initiative), (Level.FEATURE, item.feature)):
            if ref is not None:
                more_labels, more_components, more_lines = self._collapse(attached, ref)
                labels += more_labels
                components += more_components
                lines += more_lines
        if mapping.how in (Materialization.PARENT, Materialization.LABEL):
            labels.append(mapping.ref or "")
        if item.external_id:
            labels.append(XID + item.external_id)
        if len(item.assignees) > 1:
            raise ValidationError(f"Jira takes one assignee; got {len(item.assignees)}")

        fields: dict[str, Any] = {
            "project": {"key": self.project_key},
            "issuetype": {"id": board.resolved[level]} if mapping.how is Materialization.TYPE else None,
            "summary": item.title,
        }
        if fields["issuetype"] is None:  # a LABEL / PARENT level rides the story type
            fields["issuetype"] = {"id": board.resolved[Level.STORY]}
        description = "\n".join(lines + ([item.description] if item.description else []))
        if description:
            fields["description"] = adf.render(description)
        if item.parent is not None:
            fields["parent"] = self._parent_field(item.parent)
        if labels:
            fields["labels"] = self._labels_for_write(labels)
        if item.assignees:
            fields["assignee"] = {"accountId": self._member_id(item.assignees[0])}
        if components:
            fields["components"] = [{"id": self._component_id(c)} for c in _dedupe(components)]
        if item.iteration:
            fields[self._sprint_field or "sprint"] = int(self._sprint_id(item.iteration))

        rec = self._t.request("POST", "/rest/api/3/issue", body={"fields": fields})
        issue_id = str(rec["id"])
        if item.external_id:
            self._created[item.external_id] = issue_id
        created = self.get_item(issue_id)
        if created.state is not item.state:
            self._transition(issue_id, item.state)
            created = self.get_item(issue_id)
        return replace(created, initiative=item.initiative, feature=item.feature)

    def _transition(self, ident: str, state: State) -> None:
        target = self._state_id[state]
        answer = self._t.request("GET", f"/rest/api/3/issue/{ident}/transitions") or {}
        options = answer.get("transitions") or []
        hit = next((t for t in options if str((t.get("to") or {}).get("id")) == target), None)
        if hit is None:
            have = ", ".join(f"{t.get('name')} → {(t.get('to') or {}).get('name')}" for t in options) or "(none)"
            raise ValidationError(f"no transition from {ident}'s status to {self.config.states[state]!r} "
                                  f"(available: {have})")
        self._t.request("POST", f"/rest/api/3/issue/{ident}/transitions", body={"transition": {"id": str(hit["id"])}})

    def update_item(self, ref: ItemRef | str, patch: ItemPatch) -> WorkItem:
        if patch.is_empty():
            raise ValidationError("nothing to update: the patch is empty")
        self._ready()
        ident = self._ident(ref)
        if patch.feature is not None:
            raise Unsupported("feature collapses on Jira; it is written at creation, by the collapse rule")
        fields: dict[str, Any] = {}
        if patch.title is not None:
            fields["summary"] = patch.title
        if patch.description is not None:
            fields["description"] = adf.render(patch.description)
        if patch.assignees is not None:
            if len(patch.assignees) > 1:
                raise ValidationError(f"Jira takes one assignee; got {len(patch.assignees)}")
            fields["assignee"] = {"accountId": self._member_id(patch.assignees[0])} if patch.assignees else None
        if patch.labels is not None:
            current = self.get_item(ident)
            keep = [XID + current.external_id] if current.external_id else []
            mapping = self.config.levels[current.level]
            if mapping.how in (Materialization.LABEL, Materialization.PARENT):  # labels never change a level
                keep.append(mapping.ref or "")
            fields["labels"] = self._labels_for_write([*patch.labels, *keep])
        if patch.parent is not None:
            fields["parent"] = self._parent_field(patch.parent)
        if fields:
            self._t.request("PUT", f"/rest/api/3/issue/{ident}", body={"fields": fields})
        if patch.state is not None:
            self._transition(ident, patch.state)
        return self.get_item(ident)

    def add_comment(self, comment: Comment) -> Comment:
        self._ready()
        ident = self._ident(comment.item)
        rec = self._t.request("POST", f"/rest/api/3/issue/{ident}/comment", body={"body": adf.render(comment.body)}) or {}
        author = rec.get("author") or {}
        return replace(
            comment,
            id=str(rec["id"]) if rec.get("id") is not None else None,
            author=author.get("displayName") or author.get("accountId"),
            created_at=_datetime(rec.get("created")),
        )

    def create_iteration(self, iteration: Iteration) -> Iteration:
        self._ready()
        if not self.config.naming.iteration_name_ok(iteration.name):
            raise ValidationError(
                f"iteration name {iteration.name!r} does not match naming.iteration {self.config.naming.iteration!r}"
            )
        # find-or-create by name, off the board's own list (a YYYYMM name also reads as a sprint id)
        board_sprints = self._t.get_all(f"/rest/agile/1.0/board/{self.board_id}/sprint")
        found = next((s for s in board_sprints if s.get("name") == iteration.name), None)
        if found is not None:
            sprint = existing_iteration(self._to_iteration(found), iteration)
        else:
            body: dict[str, Any] = {"name": iteration.name, "originBoardId": int(self.board_id)}
            if iteration.start:
                body["startDate"] = self._edge(iteration.start, time(0, 0))
            if iteration.end:
                body["endDate"] = self._edge(iteration.end, time(23, 59))
            rec = self._t.request("POST", "/rest/agile/1.0/sprint", body=body)
            sprint = replace(iteration, id=str(rec["id"]), state=IterationState.PLANNED)
        sprint_id = sprint.id or ""
        self._sprints[sprint_id] = sprint_id
        self._sprints[iteration.name] = sprint_id
        today = self._today()
        if sprint.state is IterationState.PLANNED and sprint.start and sprint.end and sprint.start <= today <= sprint.end:
            try:  # dates decide: a sprint covering today is active, whenever it was created
                self._t.request("POST", f"/rest/agile/1.0/sprint/{sprint_id}", body={"state": "active"})
            except ValidationError as exc:
                raise ValidationError(
                    f"{'found' if found else 'created'} sprint {iteration.name!r} but Jira would not start it: "
                    f"{exc} (another sprint may be active; this board has no parallel sprints)"
                ) from None
        return self.get_iteration(sprint_id)

    def move_to_iteration(self, items: Sequence[ItemRef | str], iteration: str) -> None:
        self._ready()
        sprint_id = self._sprint_id(iteration)
        idents = _dedupe(self._ident(i) for i in items)
        for n in range(0, len(idents), _MOVE_BATCH):
            self._t.request("POST", f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                            body={"issues": idents[n : n + _MOVE_BATCH]})

    def close_iteration(self, iteration: str) -> Iteration:
        self._ready()
        current = self.get_iteration(iteration)
        if current.state is IterationState.CLOSED:
            return current
        if current.state is IterationState.PLANNED:
            raise ValidationError(f"sprint {current.name!r} has not started; Jira closes only an active sprint")
        self._t.request("POST", f"/rest/agile/1.0/sprint/{current.id}", body={"state": "closed"})
        closed = self.get_iteration(current.id or iteration)
        if closed.state is not IterationState.CLOSED:
            raise ValidationError(f"sprint {current.name!r} did not close: Jira reports it {closed.state.value}")
        return closed


# --- helpers ---------------------------------------------------------------------------


def _jql(value: str) -> str:
    """A value for inside a double-quoted JQL string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _label_ok(label: str) -> bool:
    return bool(label) and len(label) <= 255 and not re.search(r"\s", label)


def _current_sprint(value: Any) -> str | None:
    """The Sprint field lists every sprint an issue has been in; the open
    one (active, else future) is the issue's iteration, else the last."""
    if not isinstance(value, list) or not value:
        return None
    sprints = [s for s in value if isinstance(s, dict)]
    for wanted in ("active", "future"):
        hit = next((s for s in sprints if s.get("state") == wanted), None)
        if hit is not None:
            return str(hit["id"])
    return str(sprints[-1]["id"]) if sprints else None


def _zone(name: Any) -> tzinfo:
    try:
        return ZoneInfo(str(name)) if name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _dedupe(values) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        seen.setdefault(v, None)
    return list(seen)


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)  # Jira writes +0000
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
