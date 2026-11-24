"""The ClickUp adapter (Phase 8; live findings from the probe,
probes/README.md 2026-11-23).

**The read side has run live; the write side has not.** Each write below
is built from ClickUp's API reference (read 2026-11-23) and proven so far
only against the fake. The conformance suite is its live proof, on a
throwaway Space.

How the canonical model lands on a ClickUp Space:

- **The board is one Space.** A personal token sees every Space its owner
  does, so each task read is checked against the configured Space, and one
  outside it is `NotFound`. Searches name the Space's own Lists. **Every
  write to a task starts with that read**, so nothing outside the Space is
  ever written.
- Levels are **task types** (`type`): ClickUp's standard task is type 0,
  named `Task` here; a custom task type goes by its name or id. A level may
  instead be marked by a tag (`label`, or `parent`). ClickUp tells levels
  apart by type alone, so two levels on one type are a config problem. A
  marker tag outranks the type. A task with neither reads as a task when
  it has a parent and as a story when it has none.
- The parent chain is the task's `parent` at every level; subtasks nest.
- **A new item goes into `connection.list`**, the board's home List, unless
  it has a parent: ClickUp keeps a subtask in its parent's List, so it goes
  there. A List is therefore never a feature.
- Initiative and Feature **collapse**: a container level is not wired, and
  ClickUp has no components. A collapse rule's tag is written in lowercase.
- States are the Space's **statuses**, by name, ignoring case, and a status
  is set by its name, in the create or the update itself. A status the
  config does not name reads by its type: `open` and `unstarted` as
  backlog, `custom` as in progress, `done` and `closed` as done. A List
  with statuses of its own is not checked.
- Labels are the Space's **tags**. ClickUp stores a tag in lowercase, so a
  label with a capital in the config is a problem. A tag goes on a task
  with a POST and **comes off with a DELETE**, the one DELETE this adapter
  sends: the task and the Space's tag both stay (transport.py). A tag the
  Space lacks (a collapse rule's, the first time) is made in the Space
  first.
- **The idempotency key** is a text custom field, named by
  `connection.xid_field` and written in the create call. The lookup asks
  for an exact match (`==`, case-sensitive in the probe) and then compares
  each task's own value, so an answer that ignored the filter still finds
  the right task or none. The field must be on every List an item can land
  in: add it to the Space.
- Members are the workspace's (`GET /team`): an assignee is a username, an
  email or a user id.
- Iterations are the Lists of the Folder named by `connection.sprint_folder`
  (optional; without it the board has none). Nothing in a Folder's record
  marks it as a sprint Folder, so the config names it. A sprint List
  carries its start and end as instants, and its state comes from them: an
  archived one is closed. A task's iteration is the sprint List it sits in
  or was added to: the active one, else a planned one, else the last.
- **A task enters a sprint by being added to its List** (Tasks in Multiple
  Lists), which leaves it in its own List and in any earlier sprint. The
  API cannot make a sprint (a List takes no start date) or close one, so
  `create_iteration` only finds, and `close_iteration` only confirms: a
  sprint Folder makes its next sprint, and a sprint closes when its end
  passes.
- A List read returns a task added to the List only with
  `include_timl=true`; the workspace-wide read never does. So
  `find_items(iteration=…)` reads the sprint List, and every other search
  reads the workspace by the Space's List ids, where each task comes back
  once, from its own List.
- Descriptions are Markdown both ways (`markdown_content` in, and every
  task read asks for `markdown_description`; where a read leaves it out,
  the plain `description` stands in). A comment's Markdown goes as its
  text.
- Dates are instants in milliseconds, read back as the day in the token
  owner's time zone. A date-only due date sits at 04:00 in that zone, and
  that is what is written. Where the zone cannot be resolved (Python on
  Windows without `tzdata`), noon UTC is written, the same day across the
  Americas and Europe.
- A task's key is its custom task id (`TST-12`), where the Space has a
  prefix; `get_item` takes either. An id that names no task is `NotFound`
  (ClickUp answers it 401, which the transport maps).
- Not wired: custom fields (`[fields]` is a config problem) and links.

No delete: nothing here removes a task, a List, a comment or a Space's
tag. tests/test_adapter_guide.py counts the DELETEs in this file: one.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from time import sleep as _sleep
from typing import Any, Callable, Iterable, Sequence
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
    ValidationError,
    existing_iteration,
)
from adapters.clickup.transport import API, ClickUpTransport, Transport, rows
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

STANDARD = TypeInfo("0", "Task", is_default=True)  # ClickUp's own task type; the custom ones are listed
# A status the config did not name reads by ClickUp's own type for it.
_TYPE_TO_STATE = {"open": State.BACKLOG, "unstarted": State.BACKLOG, "custom": State.IN_PROGRESS,
                  "done": State.DONE, "closed": State.DONE}
_CUSTOM_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")  # a custom task id, such as TST-12
_SCAN_PAGES = 10  # pages of 100 a search reads before it stops
# ClickUp gives a new task its custom id a moment after the create answers (seen live, 2026-11-24):
# the seconds to wait before each further read of a task that came back without one.
_KEY_WAITS = (1.0, 2.0)
_TEXT_FIELDS = ("short_text", "text")  # the custom field types that can hold the idempotency key
_DATE_HOUR = 4  # where ClickUp puts a date with no time, in the owner's zone (probe, 2026-11-23)
TAG_FG, TAG_BG = "#ffffff", "#667684"  # the colours of a tag this adapter makes; ClickUp requires both
_NO_XID = ("this board names no idempotency field (connection.xid_field), so an item cannot be found by its "
           "external id; search by title instead")
_NO_LINKS = "links are not written on ClickUp yet; put the URL in the description or a comment"
_NO_FIELDS = "custom fields are not wired on ClickUp yet"


class ClickUpAdapter(Adapter):
    backend = "clickup"

    def __init__(
        self,
        config: BoardConfig,
        transport: Transport | None = None,
        *,
        secret: Callable[[str], str] = secrets.get,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = _sleep,
    ) -> None:
        if config.backend is not Backend.CLICKUP:
            raise ValueError(f"ClickUpAdapter got a {config.backend.value} config")
        super().__init__(config)
        conn = config.connection
        self.workspace = conn.ids["workspace"]
        self.space = conn.ids["space"]
        self.sprint_folder = conn.ids.get("sprint_folder")
        self.home_list = conn.ids.get("list")
        self.xid_field = conn.ids.get("xid_field")
        self._t: Transport = transport or ClickUpTransport(lambda: secret(conn.token_env), base_url=conn.base_url or API)
        self._now = now  # a sprint's state comes from its instants, so the clock is an instant too
        self._sleep = sleep
        self._keyed: bool | None = None  # whether the Space issues custom task ids, once a task has shown it
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
        self._status_of_state: dict[State, str] = {}  # state -> the status name as the Space spells it
        self._lists: list[str] = []  # every List in the Space that is not archived
        self._home: str | None = None  # the List a new item with no parent goes into
        self._xid: str | None = None  # the idempotency field's id
        self._tags: set[str] = set()  # the Space's tags
        self._members: dict[str, int] = {}  # lower username / email / id -> user id
        self._member_name: dict[int, str] = {}
        self._me: str | None = None  # the token owner, who writes every comment
        self._sprint_folder_id: str | None = None
        self._sprints: dict[str, dict[str, Any]] = {}  # sprint List id -> its record
        self._sprint_names: dict[str, str] = {}  # sprint List name -> id
        self._zone: tzinfo = timezone.utc
        self._zone_known = False
        self._created: dict[str, str] = {}  # external_id -> the task this process created, should the search lag

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
        me = (self._t.request("GET", "/user") or {}).get("user") or {}
        zone = _zone(me.get("timezone"))
        self._zone, self._zone_known = zone or timezone.utc, zone is not None
        self._me = me.get("username") or None
        team = next((t for t in self._t.get_all("/team") if isinstance(t, dict) and str(t.get("id")) == self.workspace), None)
        custom = [t for t in self._t.get_all(f"/team/{self.workspace}/custom_item") if isinstance(t, dict)]
        types = [STANDARD] + [TypeInfo(str(t["id"]), str(t.get("name") or "")) for t in custom if t.get("id") is not None]
        space = self._t.request("GET", f"/space/{self.space}") or {}
        states = [StateInfo(str(s.get("id") or s.get("status") or ""), str(s.get("status") or ""), s.get("type"))
                  for s in space.get("statuses") or [] if isinstance(s, dict)]
        tags = [NamedRef(t["name"], t["name"]) for t in self._t.get_all(f"/space/{self.space}/tag")
                if isinstance(t, dict) and isinstance(t.get("name"), str)]
        self._tags = {t.name for t in tags}
        folders = [f for f in self._t.get_all(f"/space/{self.space}/folder", {"archived": "false"}) if isinstance(f, dict)]
        loose = [x for x in self._t.get_all(f"/space/{self.space}/list", {"archived": "false"}) if isinstance(x, dict)]

        problems: list[str] = []
        members: list[NamedRef] = []
        for entry in (team or {}).get("members") or []:
            user = entry.get("user") if isinstance(entry, dict) else None
            if isinstance(user, dict) and user.get("id") is not None:
                members.append(NamedRef(str(user["id"]), str(user.get("username") or user.get("email") or user["id"]),
                                        {"email": user.get("email")}))
        self._index_members(members)

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
        problems += self._check_home(containers)

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
            members=tuple(members),
            containers=tuple(containers),
            iterations=tuple(iterations),
            resolved=resolved,
            problems=tuple(problems),
        )
        return self._board

    def _index_members(self, members: Sequence[NamedRef]) -> None:
        self._members, self._member_name = {}, {}
        for m in members:
            uid = int(m.id)
            self._members[m.id] = uid
            self._members[m.name.lower()] = uid
            if m.extra.get("email"):
                self._members[str(m.extra["email"]).lower()] = uid
            self._member_name[uid] = m.name

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

    def _check_home(self, lists: Sequence[NamedRef]) -> list[str]:
        """Where a new item goes and where its idempotency key is kept:
        `connection.list` and `connection.xid_field`, against the Space."""
        problems: list[str] = []
        self._home = self._xid = None
        names = ", ".join(x.name for x in lists) or "(none)"
        wanted = self.home_list
        home = next((x for x in lists if wanted == x.id or wanted.lower() == x.name.lower()), None) if wanted else None
        if not wanted:
            problems.append(f"connection.list: name the List a new item is filed in (lists: {names})")
        elif home is None:
            problems.append(f"connection.list: no List {wanted!r} in the Space outside its sprint Folder (lists: {names})")
        else:
            self._home = home.id
        field = self.xid_field
        if not field:
            problems.append("connection.xid_field: name the text custom field that holds an item's idempotency key "
                            "(add a short text field to the Space, so every List carries it)")
        elif home is not None:
            found = [f for f in self._t.get_all(f"/list/{home.id}/field") if isinstance(f, dict)]
            hit = next((f for f in found if field == str(f.get("id")) or field.lower() == str(f.get("name") or "").lower()), None)
            if hit is None:
                have = ", ".join(str(f.get("name")) for f in found) or "(none)"
                problems.append(f"connection.xid_field: no custom field {field!r} on the List {home.name!r} (fields: {have})")
            elif hit.get("type") not in _TEXT_FIELDS:
                problems.append(f"connection.xid_field: {hit.get('name')!r} is a {hit.get('type')} field; the idempotency "
                                "key needs a text one (short_text or text)")
            else:
                self._xid = str(hit["id"])
        return problems

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
        self._state_of_status, self._status_of_state = {}, {}
        for state, name in cfg.states.items():
            hit = next((s for s in states if s.name.lower() == name.lower()), None)
            if hit is None:
                problems.append(f"states.{state.value}: no status named {name!r} in the Space (statuses: {state_names})")
            else:
                self._state_of_status[hit.name.lower()] = state
                self._status_of_state[state] = hit.name

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

    def _member_id(self, who: str) -> int:
        hit = self._members.get(who) or self._members.get(who.lower())
        if hit is None:
            have = ", ".join(sorted(self._member_name.values())) or "(none)"
            raise ValidationError(f"no member {who!r} in the workspace (members: {have})")
        return hit

    def _status(self, state: State) -> str:
        name = self._status_of_state.get(state)
        if name is None:
            raise ValidationError(f"this board names no status for {state.value} (states.{state.value})")
        return name

    def _collapse(self, level: Level, ref: ItemRef) -> tuple[list[str], list[str]]:
        """Apply the collapse rule for an attachment of `level`; returns
        (tags, description lines) to add."""
        rule: CollapseRule | None = self.config.levels[level].collapse
        if rule is None or rule.target is CollapseTarget.COMPONENT:
            raise Unsupported(f"a {level.value} attachment has no realization on this board "
                              f"(levels.{level.value} is not collapsed to a label or a description_line)")
        text = rule.template.format(level=level.value, name=ref.key or ref.id, id=ref.id, key=ref.key or "")
        if rule.target is CollapseTarget.LABEL:
            return [text.strip().lower()], []
        return [], [text]

    def _marker(self, level: Level) -> str | None:
        """The tag that marks a LABEL / PARENT level, which no label change may take off."""
        mapping = self.config.levels.get(level)
        if mapping is not None and mapping.how in (Materialization.LABEL, Materialization.PARENT):
            return mapping.ref
        return None

    def _missing_tags(self, tags: Iterable[str]) -> list[str]:
        """The tags the Space does not have yet, after one fresh read if any looks new."""
        tags = list(tags)
        if any(t not in self._tags for t in tags):
            self._tags = {t["name"] for t in self._t.get_all(f"/space/{self.space}/tag")
                          if isinstance(t, dict) and isinstance(t.get("name"), str)}
        return [t for t in tags if t not in self._tags]

    def _make_tags(self, tags: Iterable[str]) -> None:
        for tag in tags:
            self._t.request("POST", f"/space/{self.space}/tag", body={"tag": {"name": tag, "tag_fg": TAG_FG, "tag_bg": TAG_BG}})
            self._tags.add(tag)

    # -- conversions ---------------------------------------------------------------

    def _day(self, value: Any) -> date | None:
        """A ClickUp instant (milliseconds) as the day in the token owner's zone."""
        moment = _instant(value)
        return moment.astimezone(self._zone).date() if moment else None

    def _stamp(self, day: date) -> int:
        """A day as the instant ClickUp keeps for a date with no time: 04:00
        in the owner's zone, or noon UTC where that zone is unknown here."""
        if self._zone_known:
            moment = datetime.combine(day, time(_DATE_HOUR), tzinfo=self._zone)
        else:
            moment = datetime.combine(day, time(12), tzinfo=timezone.utc)
        return int(moment.timestamp() * 1000)

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
        mine = [i for i in _lists_of(rec) if i in self._sprints]
        for wanted in (IterationState.ACTIVE, IterationState.PLANNED):
            hit = next((i for i in mine if self._sprint_state(self._sprints[i]) is wanted), None)
            if hit is not None:
                return hit
        return mine[-1] if mine else None

    def _level_of(self, rec: dict[str, Any]) -> Level:
        marked = next((self._level_of_tag[t] for t in _tags_of(rec) if t in self._level_of_tag), None)
        if marked is not None:  # a marker tag outranks the type
            return marked
        type_id = str(rec.get("custom_item_id") or 0)  # null and 0 both mean the standard task
        if type_id in self._level_of_type:
            return self._level_of_type[type_id]
        return Level.TASK if rec.get("parent") else Level.STORY

    def _external_id(self, rec: dict[str, Any]) -> str | None:
        if self._xid is None:
            return None
        for field in rec.get("custom_fields") or []:
            if isinstance(field, dict) and str(field.get("id")) == self._xid:
                value = field.get("value")
                return value if isinstance(value, str) and value else None
        return None

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
            external_id=self._external_id(rec),
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
        self._note_key(rec)
        return rec

    def _note_key(self, rec: dict[str, Any]) -> None:
        """Learn from a task whether the Space issues custom task ids. One that has one says
        yes. One over a minute old without one says no; a newer one says nothing yet."""
        if rec.get("custom_id"):
            self._keyed = True
        elif self._keyed is None:
            made = _instant(rec.get("date_created"))
            if made is not None and self._now() - made > timedelta(minutes=1):
                self._keyed = False

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
        if external_id and self._xid is None:
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
        if external_id:  # `==` is exact on a text field (probe); each task's own value is compared below as well
            params["custom_fields"] = json.dumps([{"field_id": self._xid, "operator": "==", "value": external_id}])
        words = query.lower().split()
        found: list[WorkItem] = []
        for page in range(_SCAN_PAGES):
            body = self._t.request("GET", path, params={**params, "page": page}) or {}
            recs = [r for r in rows(body) if isinstance(r, dict) and r.get("id") and self._here(r)]
            known = {str(r["id"]): r for r in recs}
            for rec in recs:
                item = self._to_item(rec, known)
                if external_id and item.external_id != external_id:
                    continue
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
        made = self._created.get(external_id) if external_id else None
        if made and not sprint_id and all(i.id != made for i in found):  # the search has not caught up yet
            try:
                item = self.get_item(made)
            except NotFound:
                item = None
            if (item is not None and item.external_id == external_id and (level is None or item.level is level)
                    and (state is None or item.state is state) and (not label or label.lower() in item.labels)):
                found.append(item)
        return found[:limit]

    # -- write ---------------------------------------------------------------------

    def create_item(self, item: WorkItem) -> WorkItem:
        item.check()
        board = self._ready()
        level, mapping = item.level, self.config.levels.get(item.level)
        if mapping is None:
            raise Unsupported(f"this board has no {level.value} level (levels.{level.value} is not in the config)")
        if mapping.how is Materialization.NONE:
            raise Unsupported(f"levels.{level.value} collapses on this board; nothing to create")
        if item.links:
            raise Unsupported(_NO_LINKS)
        if item.fields:
            raise Unsupported(_NO_FIELDS)
        if item.component:
            raise Unsupported("ClickUp has no components; use a label")

        tags = [label.lower() for label in item.labels]
        lines: list[str] = []
        for attached, ref in ((Level.INITIATIVE, item.initiative), (Level.FEATURE, item.feature)):
            if ref is not None:
                more_tags, more_lines = self._collapse(attached, ref)
                tags += more_tags
                lines += more_lines
        if mapping.how is Materialization.TYPE:
            type_id = board.resolved[level]
        else:  # a LABEL / PARENT level rides the story type, or the standard task
            tags.append(mapping.ref or "")
            type_id = board.resolved[Level.STORY] if Level.STORY in self._level_of_type.values() else STANDARD.id
        tags = _dedupe(tags)

        body: dict[str, Any] = {"name": item.title, "custom_item_id": int(type_id), "status": self._status(item.state)}
        description = "\n\n".join(lines + ([item.description] if item.description else []))
        if description:
            body["markdown_content"] = description
        if tags:
            body["tags"] = tags
        if item.assignees:
            body["assignees"] = _dedupe(self._member_id(a) for a in item.assignees)
        if item.start_date:
            body.update(start_date=self._stamp(item.start_date), start_date_time=False)
        if item.target_date:
            body.update(due_date=self._stamp(item.target_date), due_date_time=False)
        if item.external_id:
            body["custom_fields"] = [{"id": self._xid, "value": item.external_id}]
        sprint_id = self._sprint_id(item.iteration) if item.iteration else None
        list_id = self._home
        if item.parent is not None:  # ClickUp keeps a subtask in its parent's List
            above = self._task(self._ident(item.parent))
            body["parent"] = str(above["id"])
            list_id = str((above.get("list") or {}).get("id") or self._home)
        new_tags = self._missing_tags(tags)

        # everything above read or refused; from here on it writes
        self._make_tags(new_tags)
        rec = self._t.request("POST", f"/list/{list_id}/task", body=body) or {}
        if not rec.get("id"):
            raise ValidationError(f"ClickUp answered the create of {item.title!r} without a task id")
        task_id = str(rec["id"])
        if item.external_id:
            self._created[item.external_id] = task_id
        if sprint_id and sprint_id != list_id:
            self._t.request("POST", f"/list/{sprint_id}/task/{task_id}")
        created = self.get_item(task_id)
        if created.key is None and self._keyed is not False:  # the custom id may be a moment behind
            for pause in _KEY_WAITS:
                self._sleep(pause)
                created = self.get_item(task_id)
                if created.key is not None:
                    break
        return replace(created, initiative=item.initiative, feature=item.feature)

    def update_item(self, ref: ItemRef | str, patch: ItemPatch) -> WorkItem:
        if patch.is_empty():
            raise ValidationError("nothing to update: the patch is empty")
        self._ready()
        if patch.feature is not None:
            raise Unsupported("feature collapses on ClickUp; it is written at creation, by the collapse rule")
        if patch.links:
            raise Unsupported(_NO_LINKS)
        if patch.fields:
            raise Unsupported(_NO_FIELDS)
        rec = self._task(self._ident(ref))  # in this Space, or NotFound before anything is written
        task_id = str(rec["id"])
        body: dict[str, Any] = {}
        if patch.title is not None:
            body["name"] = patch.title
        if patch.description is not None:
            if patch.description:
                body["markdown_content"] = patch.description
            else:
                body["description"] = " "  # ClickUp's own way to clear one
        if patch.state is not None:
            body["status"] = self._status(patch.state)
        if patch.assignees is not None:
            want = {self._member_id(a) for a in patch.assignees}
            have = {int(a["id"]) for a in rec.get("assignees") or [] if isinstance(a, dict) and a.get("id") is not None}
            if want != have:
                body["assignees"] = {"add": sorted(want - have), "rem": sorted(have - want)}
        if patch.parent is not None:
            body["parent"] = str(self._task(self._ident(patch.parent))["id"])
        if patch.start_date is not None:
            body.update(start_date=self._stamp(patch.start_date), start_date_time=False)
        if patch.target_date is not None:
            body.update(due_date=self._stamp(patch.target_date), due_date_time=False)
        on: list[str] = []
        off: list[str] = []
        if patch.labels is not None:
            have_tags = _tags_of(rec)
            marker = self._marker(self._level_of(rec))  # labels never change a level
            want_tags = _dedupe([*(label.lower() for label in patch.labels), *([marker] if marker else [])])
            on = [t for t in want_tags if t not in have_tags]
            off = [t for t in have_tags if t not in want_tags]
            slashed = [t for t in (*on, *off) if "/" in t]
            if slashed:  # the tag's name is in the address, and ClickUp takes no form of a slash there (probe, 2026-11-24)
                raise Unsupported(f"ClickUp's API cannot add a tag with a slash in its name to a task, or take one "
                                  f"off ({', '.join(slashed)}): change it in ClickUp. Nothing was written")
        new_tags = self._missing_tags(on)

        # everything above read or refused; from here on it writes
        self._make_tags(new_tags)
        if body:
            self._t.request("PUT", f"/task/{task_id}", body=body)
        for tag in on:
            self._t.request("POST", _tag_path(task_id, tag))
        for tag in off:  # the tag leaves this task; the task and the Space's tag both stay
            self._t.request("DELETE", _tag_path(task_id, tag))
        return self.get_item(task_id)

    def add_comment(self, comment: Comment) -> Comment:
        self._ready()
        rec = self._task(self._ident(comment.item))
        answer = self._t.request("POST", f"/task/{rec['id']}/comment",
                                 body={"comment_text": comment.body, "notify_all": False}) or {}
        return replace(
            comment,
            id=str(answer["id"]) if answer.get("id") is not None else None,
            author=self._me,
            created_at=_instant(answer.get("date")),
        )

    def create_iteration(self, iteration: Iteration) -> Iteration:
        self._ready()
        try:
            sprint_id = self._sprint_id(iteration.name)
        except NotFound:
            raise Unsupported(
                f"ClickUp's API cannot make a sprint, so {iteration.name!r} has to be made in ClickUp "
                "(a sprint Folder makes its next sprint itself); then ask again"
            ) from None
        return existing_iteration(self.get_iteration(sprint_id), iteration)

    def move_to_iteration(self, items: Sequence[ItemRef | str], iteration: str) -> None:
        self._ready()
        sprint = self.get_iteration(iteration)
        if sprint.state is IterationState.CLOSED:
            raise ValidationError(f"sprint {sprint.name!r} is closed ({sprint.start}–{sprint.end}); pick an open one")
        recs = [self._task(ident) for ident in _dedupe(self._ident(i) for i in items)]  # each in this Space, or NotFound
        for rec in {str(r["id"]): r for r in recs}.values():  # one named by its id and by its key is one task
            if sprint.id not in _lists_of(rec):  # adding it leaves it in its own List and in any earlier sprint
                self._t.request("POST", f"/list/{sprint.id}/task/{rec['id']}")

    def close_iteration(self, iteration: str) -> Iteration:
        self._ready()
        current = self.get_iteration(iteration)
        if current.state is IterationState.CLOSED:
            return current
        raise Unsupported(f"ClickUp closes a sprint itself when its end passes, and {current.name!r} runs to "
                          f"{current.end}; nothing here can close it sooner")


# --- helpers ---------------------------------------------------------------------------


def _tag_problem(tag: str, have: set[str], names: str) -> str | None:
    """Why a tag the config names cannot be used as written, or None."""
    if tag != tag.lower():
        return f"ClickUp stores tags in lowercase, so {tag!r} would read back as {tag.lower()!r}; write it in lowercase"
    if tag not in have:
        return f"no tag {tag!r} in the Space (tags: {names})"
    return None


def _tag_path(task_id: str, tag: str) -> str:
    return f"/task/{task_id}/tag/{urllib.parse.quote(tag, safe='')}"


def _tags_of(rec: dict[str, Any]) -> list[str]:
    return [str(t.get("name") or "").lower() for t in rec.get("tags") or [] if isinstance(t, dict) and t.get("name")]


def _lists_of(rec: dict[str, Any]) -> list[str]:
    """The List a task sits in, then the Lists it was added to."""
    return ([str((rec.get("list") or {}).get("id") or "")]
            + [str(x.get("id")) for x in rec.get("locations") or [] if isinstance(x, dict)])


def _dedupe(values: Iterable[Any]) -> list[Any]:
    seen: dict[Any, None] = {}
    for v in values:
        seen.setdefault(v, None)
    return list(seen)


def _instant(value: Any) -> datetime | None:
    """A ClickUp date: milliseconds since the epoch, as digits."""
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _zone(name: Any) -> tzinfo | None:
    """The named time zone, or None where this Python cannot resolve it."""
    try:
        return ZoneInfo(str(name)) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None
