"""The ClickUp adapter: the read side (Phase 8; live findings from the
probe, probes/README.md 2026-11-23).

**It reads and writes nothing yet.** Every write method raises
`Unsupported` before any call. The write side waits on decisions a read
cannot settle: where the idempotency key lives, how a task moves into a
sprint, and how a status is set.

How the canonical model lands on a ClickUp Space:

- **The board is one Space.** A personal token sees every Space its owner
  does, so each task read is checked against the configured Space, and one
  outside it is `NotFound`. Searches name the Space's own Lists.
- Levels are **task types** (`type`): ClickUp's standard task is type 0,
  named `Task` here; a custom task type goes by its name or id. A level may
  instead be marked by a tag (`label`, or `parent`). ClickUp tells levels
  apart by type alone, so two levels on one type are a config problem. A
  marker tag outranks the type. A task with neither reads as a task when
  it has a parent and as a story when it has none.
- The parent chain is the task's `parent` at every level; subtasks nest.
- Initiative and Feature **collapse**: a container level is not wired, and
  ClickUp has no components.
- States are the Space's **statuses**, by name, ignoring case. A status
  the config does not name reads by its type: `open` and `unstarted` as
  backlog, `custom` as in progress, `done` and `closed` as done. A List
  with statuses of its own is not checked.
- Labels are the Space's **tags**. ClickUp stores a tag in lowercase, so a
  label with a capital in the config is a problem.
- Iterations are the Lists of the Folder named by `connection.sprint_folder`
  (optional; without it the board has none). Nothing in a Folder's record
  marks it as a sprint Folder, so the config names it. A sprint List
  carries its start and end as instants, and its state comes from them: an
  archived one is closed. A task's iteration is the sprint List it sits in
  or was added to: the active one, else a planned one, else the last.
- A List read returns a task added to the List only with
  `include_timl=true`; the workspace-wide read never does. So
  `find_items(iteration=…)` reads the sprint List, and every other search
  reads the workspace by the Space's List ids, where each task comes back
  once, from its own List.
- Descriptions are Markdown both ways. Every task read asks for
  `markdown_description`; where a read leaves it out, the plain
  `description` stands in.
- Dates are instants in milliseconds, read back as the day in the token
  owner's time zone. A date-only due date sits at 04:00 in that zone.
- A task's key is its custom task id (`TST-12`), where the Space has a
  prefix; `get_item` takes either. An id that names no task is `NotFound`
  (ClickUp answers it 401, which the transport maps).
- Not read yet: members, custom fields (`[fields]` is a config problem),
  links, and the idempotency key (`find_items(external_id=…)` raises
  `Unsupported`).

No delete: this file sends GET and nothing else.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date, datetime, timezone, tzinfo
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from adapters.base import (
    Adapter,
    AdapterError,
    BoardDescription,
    ItemPatch,
    NamedRef,
    NotFound,
    StateInfo,
    TypeInfo,
    Unsupported,
)
from adapters.clickup.transport import API, ClickUpTransport, Transport, rows
from server import secrets
from server.config import Backend, BoardConfig
from server.model import (
    Capabilities,
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

STANDARD = TypeInfo("0", "Task", is_default=True)  # ClickUp's own task type; the custom ones are listed
# A status the config did not name reads by ClickUp's own type for it.
_TYPE_TO_STATE = {"open": State.BACKLOG, "unstarted": State.BACKLOG, "custom": State.IN_PROGRESS,
                  "done": State.DONE, "closed": State.DONE}
_CUSTOM_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")  # a custom task id, such as TST-12
_SCAN_PAGES = 10  # pages of 100 a search reads before it stops
_READ_ONLY = "ClickUp writes are not wired yet: this adapter reads the board and writes nothing"
_NO_XID = ("the idempotency key is not wired on ClickUp yet, so an item cannot be found by its external id; "
           "search by title instead")


class ClickUpAdapter(Adapter):
    backend = "clickup"

    def __init__(
        self,
        config: BoardConfig,
        transport: Transport | None = None,
        *,
        secret: Callable[[str], str] = secrets.get,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if config.backend is not Backend.CLICKUP:
            raise ValueError(f"ClickUpAdapter got a {config.backend.value} config")
        super().__init__(config)
        conn = config.connection
        self.workspace = conn.ids["workspace"]
        self.space = conn.ids["space"]
        self.sprint_folder = conn.ids.get("sprint_folder")
        self._t: Transport = transport or ClickUpTransport(lambda: secret(conn.token_env), base_url=conn.base_url or API)
        self._now = now  # a sprint's state comes from its instants, so the clock is an instant too
        self._caps = Capabilities(
            self.backend,
            config.materializations(),
            DescriptionFormat.MARKDOWN,
            states_via_transitions=False,
            native_idempotency_key=False,
            collapse=config.collapse_rules(),
        )
        self._board: BoardDescription | None = None
        # lookup tables filled by describe_board
        self._level_of_type: dict[str, Level] = {}
        self._level_of_tag: dict[str, Level] = {}  # lower marker tag -> LABEL/PARENT level
        self._state_of_status: dict[str, State] = {}  # lower status name -> state
        self._lists: list[str] = []  # every List in the Space that is not archived
        self._sprint_folder_id: str | None = None
        self._sprints: dict[str, dict[str, Any]] = {}  # sprint List id -> its record
        self._sprint_names: dict[str, str] = {}  # sprint List name -> id
        self._zone: tzinfo = timezone.utc

    # -- plumbing ------------------------------------------------------------------

    @property
    def capabilities(self) -> Capabilities:
        return self._caps

    def _ready_maps(self) -> None:
        """Reads need the lookup tables but not a clean config."""
        if self._board is None:
            self.describe_board()

    # -- describe ------------------------------------------------------------------

    def describe_board(self) -> BoardDescription:
        me = (self._t.request("GET", "/user") or {}).get("user") or {}
        self._zone = _zone(me.get("timezone"))
        custom = [t for t in self._t.get_all(f"/team/{self.workspace}/custom_item") if isinstance(t, dict)]
        types = [STANDARD] + [TypeInfo(str(t["id"]), str(t.get("name") or "")) for t in custom if t.get("id") is not None]
        space = self._t.request("GET", f"/space/{self.space}") or {}
        states = [StateInfo(str(s.get("id") or s.get("status") or ""), str(s.get("status") or ""), s.get("type"))
                  for s in space.get("statuses") or [] if isinstance(s, dict)]
        tags = [NamedRef(t["name"], t["name"]) for t in self._t.get_all(f"/space/{self.space}/tag")
                if isinstance(t, dict) and isinstance(t.get("name"), str)]
        folders = [f for f in self._t.get_all(f"/space/{self.space}/folder", {"archived": "false"}) if isinstance(f, dict)]
        loose = [x for x in self._t.get_all(f"/space/{self.space}/list", {"archived": "false"}) if isinstance(x, dict)]

        problems: list[str] = []
        sprint = None
        if self.sprint_folder:
            wanted = self.sprint_folder
            sprint = next((f for f in folders if wanted == str(f.get("id")) or wanted.lower() == str(f.get("name") or "").lower()),
                          None)
            if sprint is None:
                have = ", ".join(str(f.get("name")) for f in folders) or "(none)"
                problems.append(f"connection.sprint_folder: no Folder {wanted!r} in the Space (folders: {have})")
        self._sprint_folder_id = str(sprint["id"]) if sprint else None
        containers: list[NamedRef] = [NamedRef(str(x["id"]), str(x.get("name") or ""), {"folder": None}) for x in loose]
        self._lists = [str(x["id"]) for x in loose]
        sprint_lists: list[dict[str, Any]] = []
        for folder in folders:
            inside = [x for x in folder.get("lists") or [] if isinstance(x, dict)]
            self._lists += [str(x["id"]) for x in inside]
            if folder is sprint:
                sprint_lists += inside
            else:
                containers += [NamedRef(str(x["id"]), str(x.get("name") or ""), {"folder": folder.get("name")}) for x in inside]
        if sprint is not None:  # a finished sprint's List may be archived, and the Folder read leaves those out
            sprint_lists += [x for x in self._t.get_all(f"/folder/{sprint['id']}/list", {"archived": "true"})
                             if isinstance(x, dict)]
        self._index_sprints(sprint_lists)
        iterations = [NamedRef(sid, str(rec.get("name") or ""), self._sprint_extra(rec)) for sid, rec in self._sprints.items()]

        resolved, more = self._check_config(types, states, [t.name for t in tags])
        problems += more
        features = space.get("features") or {}
        self._board = BoardDescription(
            backend=self.backend,
            project_id=str(space.get("id") or self.space),
            project_key=None,
            project_name=space.get("name"),
            features={"enabled": sorted(k for k, v in features.items() if isinstance(v, dict) and v.get("enabled")),
                      "private": space.get("private"), "time_zone": me.get("timezone"),
                      "sprint_folder": sprint.get("name") if sprint else None},
            types=tuple(types),
            states=tuple(states),
            labels=tuple(tags),
            members=(),  # not read yet: ClickUp lists members per List
            containers=tuple(containers),
            iterations=tuple(iterations),
            resolved=resolved,
            problems=tuple(problems),
        )
        return self._board

    def _index_sprints(self, sprint_lists: Sequence[dict[str, Any]]) -> None:
        self._sprints, self._sprint_names = {}, {}
        for rec in sprint_lists:
            sid = str(rec["id"])
            self._sprints.setdefault(sid, rec)
            self._sprint_names.setdefault(str(rec.get("name") or ""), sid)

    def _sprint_extra(self, rec: dict[str, Any]) -> dict[str, Any]:
        start, end = self._day(rec.get("start_date")), self._day(rec.get("due_date"))
        return {"state": self._sprint_state(rec).value, "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None}

    def _check_config(self, types, states, tags) -> tuple[dict[Level, str], list[str]]:
        cfg = self.config
        problems: list[str] = []
        resolved: dict[Level, str] = {}
        type_names = ", ".join(t.name for t in types) or "(none)"
        tag_names = ", ".join(tags) or "(none)"
        have_tags = {t.lower() for t in tags}
        self._level_of_type, self._level_of_tag = {}, {}
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
                if mapping.collapse.target is CollapseTarget.COMPONENT:
                    problems.append(f"levels.{level.value}: ClickUp has no components; collapse it to a label "
                                    "or a description_line")
            if how is Materialization.TYPE:
                hit = next((t for t in types if ref == t.id or ref.lower() == t.name.lower()), None)
                if hit is None:
                    problems.append(f"levels.{level.value}: no task type {ref!r} in the workspace (types: {type_names})")
                elif hit.id in self._level_of_type:
                    other = self._level_of_type[hit.id].value
                    problems.append(f"levels.{level.value}: task type {hit.name!r} is already the {other} level; ClickUp "
                                    "tells levels apart by type, so give each its own type or mark one with a tag "
                                    "(the label form)")
                else:
                    resolved[level] = hit.id
                    self._level_of_type[hit.id] = level
            elif how is Materialization.CONTAINER:
                problems.append(f"levels.{level.value}: a container level is not wired on ClickUp yet; collapse it "
                                "(label or description_line)")
            elif how in (Materialization.PARENT, Materialization.LABEL):
                problem = _tag_problem(ref, have_tags, tag_names)
                if problem:
                    problems.append(f"levels.{level.value}: {problem}")
                else:
                    resolved[level] = ref
                    self._level_of_tag[ref] = level

        state_names = ", ".join(s.name for s in states) or "(none)"
        self._state_of_status = {}
        for state, name in cfg.states.items():
            hit = next((s for s in states if s.name.lower() == name.lower()), None)
            if hit is None:
                problems.append(f"states.{state.value}: no status named {name!r} in the Space (statuses: {state_names})")
            else:
                self._state_of_status[hit.name.lower()] = state

        for label in (cfg.labels.review, *cfg.labels.taxonomy):
            if label is not None:  # None: review is off
                problem = _tag_problem(label, have_tags, tag_names)
                if problem:
                    problems.append(f"labels: {problem}")
        if cfg.fields:
            problems.append("fields: custom fields are not wired on ClickUp yet; leave [fields] out for now")
        return resolved, problems

    # -- resolvers -----------------------------------------------------------------

    @staticmethod
    def _ident(ref: ItemRef | str) -> str:
        if isinstance(ref, ItemRef):
            return ref.key or ref.id
        return ref

    def _here(self, rec: dict[str, Any]) -> bool:
        """Whether a task record belongs to this board's Space."""
        return str((rec.get("space") or {}).get("id") or "") == self.space

    def _sprint_id(self, ident: str) -> str:
        if self._sprint_folder_id is None:
            raise NotFound(f"no sprint {ident!r}: this board names no sprint Folder (connection.sprint_folder)")
        hit = ident if ident in self._sprints else self._sprint_names.get(ident)
        if hit is None:  # maybe made since describe_board: read the Folder again, once
            folder = self._t.request("GET", f"/folder/{self._sprint_folder_id}") or {}
            fresh = [x for x in folder.get("lists") or [] if isinstance(x, dict)]
            self._index_sprints([*self._sprints.values(), *fresh])
            self._lists += [str(x["id"]) for x in fresh if str(x["id"]) not in self._lists]
            hit = ident if ident in self._sprints else self._sprint_names.get(ident)
        if hit is None:
            raise NotFound(f"no sprint {ident!r} in the board's sprint Folder")
        return hit

    # -- conversions ---------------------------------------------------------------

    def _day(self, value: Any) -> date | None:
        """A ClickUp instant (milliseconds) as the day in the token owner's zone."""
        moment = _instant(value)
        return moment.astimezone(self._zone).date() if moment else None

    def _sprint_state(self, rec: dict[str, Any]) -> IterationState:
        if rec.get("archived"):
            return IterationState.CLOSED
        start, end, now = _instant(rec.get("start_date")), _instant(rec.get("due_date")), self._now()
        if end and now > end:
            return IterationState.CLOSED
        if start and end and start <= now:
            return IterationState.ACTIVE
        return IterationState.PLANNED

    def _to_iteration(self, rec: dict[str, Any]) -> Iteration:
        return Iteration(str(rec.get("name") or ""), id=str(rec["id"]), start=self._day(rec.get("start_date")),
                         end=self._day(rec.get("due_date")), state=self._sprint_state(rec))

    def _current_sprint(self, rec: dict[str, Any]) -> str | None:
        """The sprint List a task sits in or was added to: the active one,
        else a planned one, else the last."""
        ids = [str((rec.get("list") or {}).get("id") or "")]
        ids += [str(x.get("id")) for x in rec.get("locations") or [] if isinstance(x, dict)]
        mine = [i for i in ids if i in self._sprints]
        for wanted in (IterationState.ACTIVE, IterationState.PLANNED):
            hit = next((i for i in mine if self._sprint_state(self._sprints[i]) is wanted), None)
            if hit is not None:
                return hit
        return mine[-1] if mine else None

    def _level_of(self, rec: dict[str, Any]) -> Level:
        tags = [str(t.get("name") or "").lower() for t in rec.get("tags") or [] if isinstance(t, dict)]
        marked = next((self._level_of_tag[t] for t in tags if t in self._level_of_tag), None)  # a marker tag outranks the type
        if marked is not None:
            return marked
        type_id = str(rec.get("custom_item_id") or 0)  # null and 0 both mean the standard task
        if type_id in self._level_of_type:
            return self._level_of_type[type_id]
        return Level.TASK if rec.get("parent") else Level.STORY

    def _to_item(self, rec: dict[str, Any], known: dict[str, dict[str, Any]] | None = None) -> WorkItem:
        """A task record as a work item. `known` holds other records by id,
        so a parent among them comes back with its level and key."""
        status = rec.get("status") or {}
        state = (self._state_of_status.get(str(status.get("status") or "").lower())
                 or _TYPE_TO_STATE.get(str(status.get("type")), State.BACKLOG))
        parent = None
        if rec.get("parent"):
            pid = str(rec["parent"])
            above = (known or {}).get(pid)
            parent = ItemRef(pid, self._level_of(above), above.get("custom_id") or None) if above else ItemRef(pid)
        text = rec.get("markdown_description")
        if not isinstance(text, str):
            text = rec.get("description") or ""
        return WorkItem(
            level=self._level_of(rec),
            title=str(rec.get("name") or ""),
            description=str(text).rstrip("\n"),
            id=str(rec["id"]),
            key=rec.get("custom_id") or None,
            parent=parent,
            state=state,
            assignees=tuple(str(a.get("username") or a.get("id")) for a in rec.get("assignees") or [] if isinstance(a, dict)),
            labels=tuple(str(t["name"]) for t in rec.get("tags") or [] if isinstance(t, dict) and t.get("name")),
            iteration=self._current_sprint(rec),
            start_date=self._day(rec.get("start_date")),
            target_date=self._day(rec.get("due_date")),
        )

    # -- read ----------------------------------------------------------------------

    def _task(self, ident: str) -> dict[str, Any]:
        """One task by its id or its custom id, if it is in this Space."""
        params: dict[str, Any] = {"include_markdown_description": "true"}
        if _CUSTOM_ID.match(ident):
            params.update(custom_task_ids="true", team_id=self.workspace)
        rec = self._t.request("GET", f"/task/{urllib.parse.quote(ident, safe='')}", params=params)
        if not isinstance(rec, dict) or not rec.get("id") or not self._here(rec):
            raise NotFound(f"no task {ident!r} in this board's Space")
        return rec

    def get_item(self, ref: ItemRef | str) -> WorkItem:
        self._ready_maps()
        rec = self._task(self._ident(ref))
        known: dict[str, dict[str, Any]] = {}
        if rec.get("parent"):  # one more read, so the parent comes back with its level and key
            try:
                above = self._task(str(rec["parent"]))
                known[str(above["id"])] = above
            except AdapterError:
                pass  # the parent is out of reach: the bare id still names it
        return self._to_item(rec, known)

    def get_iteration(self, iteration: str) -> Iteration:
        self._ready_maps()
        sprint_id = self._sprint_id(iteration)
        rec = self._t.request("GET", f"/list/{sprint_id}") or {}
        if not rec.get("id"):
            raise NotFound(f"no sprint {iteration!r} in the board's sprint Folder")
        self._sprints[sprint_id] = rec
        return self._to_iteration(rec)

    def find_items(self, query: str = "", *, external_id=None, level=None, state=None, iteration=None,
                   label=None, limit=50) -> list[WorkItem]:
        self._ready_maps()
        if external_id:
            raise Unsupported(_NO_XID)
        if level is not None and not self._caps.materializes(level):
            return []  # a collapsed or absent level has no items of its own
        params: dict[str, Any] = {"subtasks": "true", "include_closed": "true", "include_markdown_description": "true"}
        sprint_id = self._sprint_id(iteration) if iteration else None
        if sprint_id:  # only the List read returns a task that was added to the sprint
            path = f"/list/{sprint_id}/task"
            params["include_timl"] = "true"
        else:
            if not self._lists:
                return []
            path = f"/team/{self.workspace}/task"
            params["list_ids[]"] = list(self._lists)
            if label:
                params["tags[]"] = [label.lower()]  # exact on this read (probe, 2026-11-23)
        words = query.lower().split()
        found: list[WorkItem] = []
        for page in range(_SCAN_PAGES):
            body = self._t.request("GET", path, params={**params, "page": page}) or {}
            recs = [r for r in rows(body) if isinstance(r, dict) and r.get("id") and self._here(r)]
            known = {str(r["id"]): r for r in recs}
            for rec in recs:
                item = self._to_item(rec, known)
                if level is not None and item.level is not level:
                    continue
                if state is not None and item.state is not state:
                    continue
                if label and label.lower() not in item.labels:
                    continue
                if sprint_id and item.iteration != sprint_id:
                    continue
                if words and not all(w in f"{item.title}\n{item.description}".lower() for w in words):
                    continue
                found.append(item)
            if len(found) >= limit or not rows(body) or body.get("last_page", True):
                break
        return found[:limit]

    # -- write: not wired ----------------------------------------------------------

    def create_item(self, item: WorkItem) -> WorkItem:
        raise Unsupported(_READ_ONLY)

    def update_item(self, ref: ItemRef | str, patch: ItemPatch) -> WorkItem:
        raise Unsupported(_READ_ONLY)

    def add_comment(self, comment: Comment) -> Comment:
        raise Unsupported(_READ_ONLY)

    def create_iteration(self, iteration: Iteration) -> Iteration:
        raise Unsupported(_READ_ONLY)

    def move_to_iteration(self, items: Sequence[ItemRef | str], iteration: str) -> None:
        raise Unsupported(_READ_ONLY)

    def close_iteration(self, iteration: str) -> Iteration:
        raise Unsupported(_READ_ONLY)


# --- helpers ---------------------------------------------------------------------------


def _tag_problem(tag: str, have: set[str], names: str) -> str | None:
    """Why a tag the config names cannot be used as written, or None."""
    if tag != tag.lower():
        return f"ClickUp stores tags in lowercase, so {tag!r} would read back as {tag.lower()!r}; write it in lowercase"
    if tag not in have:
        return f"no tag {tag!r} in the Space (tags: {names})"
    return None


def _instant(value: Any) -> datetime | None:
    """A ClickUp date: milliseconds since the epoch, as digits."""
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _zone(name: Any) -> tzinfo:
    try:
        return ZoneInfo(str(name)) if name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc
