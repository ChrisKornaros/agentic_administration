"""A fake ClickUp transport for the offline tests — never a live tracker.

Shapes follow the Phase 8 probe (probes/clickup_phase8_readonly.py, run
2026-11-23): the one-list envelopes (`custom_items`, `tags`, `folders`,
`lists`, `tasks`), a Space's statuses with their five types, a Folder
carrying its Lists, a sprint List with its start and end as millisecond
instants, a standard task's `custom_item_id` of 0, tags in lowercase, and a
task's `list` (its own), `locations` (the Lists it was added to), `parent`
and `custom_id`.

The rules it keeps are the ones that probe read: a List read returns a
task added to the List only with `include_timl=true`, a subtask only with
`subtasks=true` and a closed task only with `include_closed=true`; the
workspace-wide read takes `list_ids[]` and an exact `tags[]` and never
returns an added task; task reads page by
`page` and say `last_page`; a task reads by its custom id with
`custom_task_ids=true` and `team_id`.

From the adapter's first live read (2026-11-23): an id that names no task
is answered 401 `Team not authorized` (`OAUTH_027`), which the real
transport maps to `NotFound`, so the fake raises that. Not read yet:
whether the workspace-wide read returns `markdown_description` when asked.
The fake leaves it out there, so the tests cover the fallback. Ids are
made up.

**The writes follow ClickUp's API reference (read 2026-11-23), not a live
run.** From it: a task is created in a List (`markdown_content`, `tags`,
`status`, `assignees`, `parent`, `custom_item_id`, dates with their
`_time` flags, `custom_fields` as id and value), and a parent must be in
that same List; an update takes `assignees` as `add` and `rem`, clears a
description with a single space, and takes no tags; a tag goes on a task
with a POST and comes off with a DELETE, and a Space's tag is made with
its two colours; a task is added to a second List with a POST; a comment
answers with `id`, `hist_id` and `date`; a List's custom fields are read
from the List, and a text field's `==` filters the workspace read. The
fake refuses what the real transport refuses: any DELETE but a tag coming
off a task. Not modelled, because nothing has read it: whether a task
takes a tag its Space lacks (the fake keeps it on the task alone).
"""

from __future__ import annotations

import copy
import itertools
import json
import re
import urllib.parse
from typing import Any

from adapters.base import NotFound, Unsupported, ValidationError
from adapters.clickup.transport import allowed

WS, SPACE, OTHER_SPACE = "9001", "9101", "9102"
F_WORK, F_SPRINTS = "9201", "9202"
L_INBOX, L_WEB, L_ELSEWHERE = "9301", "9302", "9399"
T_MILESTONE, T_EPIC, T_STORY, T_BUG = 1, 1001, 1002, 1003
U_ROBIN, U_SAM = 9501, 9502
FIELD_XID, FIELD_SIZE = "fld-9701", "fld-9702"  # custom field ids; ClickUp's are UUIDs
COMMENTED = "2026-11-25T15:00:00+00:00"  # when every comment is made

_STATUSES = [("to do", "open"), ("backlog", "unstarted"), ("in progress", "custom"), ("done", "done"),
             ("cancelled", "done"), ("complete", "closed")]


def ms(text: str) -> str:
    """`2026-11-23T11:00:00+00:00` as ClickUp writes an instant: milliseconds, as digits."""
    from datetime import datetime

    return str(int(datetime.fromisoformat(text).timestamp() * 1000))


class FakeClickUp:
    """In-memory workspace + one Space + a log of every call. Unknown routes raise `NotFound`."""

    def __init__(self, *, page_size: int = 100) -> None:
        self.user = {"id": U_ROBIN, "username": "Robin", "email": "robin@example.invalid", "timezone": "America/New_York"}
        self.custom_items = [{"id": T_MILESTONE, "name": "milestone", "name_plural": None, "description": None},
                             {"id": T_EPIC, "name": "Epic", "name_plural": "Epics", "description": None},
                             {"id": T_STORY, "name": "Story", "name_plural": "Stories", "description": None},
                             {"id": T_BUG, "name": "Bug", "name_plural": "Bugs", "description": None}]
        self.statuses = [{"id": f"st{n}", "status": name, "type": kind, "orderindex": n, "color": "#000000"}
                         for n, (name, kind) in enumerate(_STATUSES)]
        self.space = {"id": SPACE, "name": "Sandbox", "private": True, "archived": False, "multiple_assignees": True,
                      "features": {"sprints": {"enabled": True}, "tags": {"enabled": True}, "time_tracking": {"enabled": False}}}
        self.tags = ["needs-review", "bug", "feature", "frontend", "feature:checkout"]
        self.members = [dict(self.user), {"id": U_SAM, "username": "Sam", "email": "sam@example.invalid"}]
        # the Space's custom fields: every List carries them
        self.fields = [{"id": FIELD_XID, "name": "External ID", "type": "short_text", "type_config": {}},
                       {"id": FIELD_SIZE, "name": "Size", "type": "drop_down", "type_config": {"options": []}}]
        self.comments: list[dict[str, Any]] = []
        self.folders = {F_WORK: "Features", F_SPRINTS: "Sprints"}
        self.lists: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.page_size = page_size
        self.calls: list[tuple[str, str, dict | None, Any]] = []
        self.fail: dict[str, Exception] = {}  # "METHOD path" -> raise
        self._ids = itertools.count(9600)
        self._keys = itertools.count(1)
        self.add_list(L_INBOX, "Inbox")
        self.add_list(L_WEB, "Web app", folder=F_WORK)

    # -- seeding (no call logged) ----------------------------------------------------

    @property
    def log(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _, _ in self.calls]

    def add_list(self, list_id: str, name: str, *, folder: str | None = None, start: str | None = None,
                 end: str | None = None, archived: bool = False) -> dict[str, Any]:
        rec = {"id": list_id, "name": name, "archived": archived, "override_statuses": False, "task_count": 0,
               "start_date": ms(start) if start else None, "due_date": ms(end) if end else None,
               "folder": {"id": folder, "name": self.folders[folder]} if folder else {"id": "0", "name": "hidden", "hidden": True},
               "space": {"id": SPACE, "name": self.space["name"]}}
        self.lists[list_id] = rec
        return rec

    def add_sprint(self, name: str, start: str, end: str, *, archived: bool = False) -> dict[str, Any]:
        return self.add_list(str(next(self._ids)), name, folder=F_SPRINTS, start=start, end=end, archived=archived)

    def add_task(self, name: str, list_id: str = L_WEB, *, type: int = 0, parent: str | None = None,
                 status: str = "backlog", tags: tuple[str, ...] = (), description: str = "", due: str | None = None,
                 start: str | None = None, added_to: tuple[str, ...] = (), assignee: bool = False,
                 space: str = SPACE, xid: str | None = None) -> dict[str, Any]:
        tid = f"86c{next(self._ids)}"
        kind = next(k for n, k in _STATUSES if n == status)
        home = self.lists.get(list_id) or {"id": list_id, "name": "Elsewhere"}
        rec = {
            "id": tid, "custom_id": f"TST-{next(self._keys)}" if space == SPACE else None, "custom_item_id": type,
            "name": name, "description": description, "text_content": description,
            "status": {"status": status, "type": kind, "orderindex": 0, "color": "#000000"},
            "parent": parent, "top_level_parent": parent,
            "tags": [{"name": t.lower(), "tag_fg": "", "tag_bg": "", "creator": U_ROBIN} for t in tags],
            "assignees": [{"id": U_ROBIN, "username": "Robin", "email": "robin@example.invalid"}] if assignee else [],
            "due_date": ms(due) if due else None, "start_date": ms(start) if start else None,
            "list": {"id": home["id"], "name": home["name"], "access": True},
            "folder": copy.deepcopy(home.get("folder") or {"id": "0", "name": "hidden"}),
            "space": {"id": space},
            "locations": [{"id": x, "name": self.lists[x]["name"]} for x in added_to],
            "linked_tasks": [], "url": f"https://example.invalid/t/{tid}", "team_id": WS,
            "custom_fields": [{**copy.deepcopy(f), **({"value": xid} if xid and f["id"] == FIELD_XID else {})}
                              for f in self.fields],
        }
        self.tasks[tid] = rec
        return rec

    def _member(self, user_id: Any) -> dict[str, Any]:
        hit = next((m for m in self.members if m["id"] == user_id), None)
        if hit is None:
            raise ValidationError(f"HTTP 400: no user {user_id!r} in the workspace")
        return {"id": hit["id"], "username": hit["username"], "email": hit["email"]}

    def _status(self, name: Any) -> dict[str, Any]:
        hit = next((s for s in self.statuses if s["status"] == str(name).lower()), None)
        if hit is None:
            raise ValidationError(f"HTTP 400: Status not found ({name!r})")
        return {"status": hit["status"], "type": hit["type"], "orderindex": hit["orderindex"], "color": hit["color"]}

    # -- the writes ------------------------------------------------------------------------

    def _create_task(self, list_id: str, body: dict[str, Any]) -> dict[str, Any]:
        parent = body.get("parent")
        if parent is not None:
            above = self.tasks.get(str(parent))
            if above is None or above["list"]["id"] != list_id:  # the reference: a parent must be in the same List
                raise ValidationError("HTTP 400: the parent is not in this List")
        status = self._status(body.get("status") or "to do")
        assignees = [self._member(a) for a in body.get("assignees") or []]
        rec = self.add_task(body["name"], list_id, type=int(body.get("custom_item_id") or 0),
                            parent=str(parent) if parent else None, status=status["status"],
                            tags=tuple(body.get("tags") or ()),
                            description=body.get("markdown_content") or body.get("description") or "")
        rec["assignees"] = assignees
        if parent:
            rec["top_level_parent"] = self.tasks[str(parent)].get("top_level_parent") or str(parent)
        for key in ("due_date", "start_date"):
            if body.get(key) is not None:
                rec[key] = str(body[key])
        for given in body.get("custom_fields") or []:  # only a field the List carries is saved
            for field in rec["custom_fields"]:
                if field["id"] == given.get("id"):
                    field["value"] = given.get("value")
        return rec

    def _update_task(self, rec: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        if "tags" in body or "custom_fields" in body:
            raise ValidationError("HTTP 400: an update takes no tags and no custom fields")
        if "parent" in body:
            if str(body["parent"]) not in self.tasks:
                raise ValidationError("HTTP 400: no such parent")
            rec["parent"] = str(body["parent"])
        if "status" in body:
            rec["status"] = self._status(body["status"])
        if "name" in body:
            rec["name"] = body["name"]
        if "markdown_content" in body:
            rec["description"] = rec["text_content"] = body["markdown_content"]
        elif "description" in body:
            rec["description"] = rec["text_content"] = body["description"].strip()
        for key in ("due_date", "start_date"):
            if key in body:
                rec[key] = str(body[key]) if body[key] is not None else None
        if "assignees" in body:
            gone = set(body["assignees"]["rem"])
            kept = [a for a in rec["assignees"] if a["id"] not in gone]
            rec["assignees"] = kept + [self._member(a) for a in body["assignees"]["add"] if all(k["id"] != a for k in kept)]
        return rec

    def _write(self, method: str, path: str, body: Any) -> Any:
        body = body or {}
        m = re.fullmatch(r"/list/(\d+)/task", path)
        if method == "POST" and m and m.group(1) in self.lists:
            return self._task_view(self._create_task(m.group(1), body), markdown=False)
        m = re.fullmatch(r"/list/(\d+)/task/([^/]+)", path)
        if method == "POST" and m and m.group(1) in self.lists and m.group(2) in self.tasks:
            rec, added = self.tasks[m.group(2)], self.lists[m.group(1)]
            if added["id"] != rec["list"]["id"] and all(x["id"] != added["id"] for x in rec["locations"]):
                rec["locations"].append({"id": added["id"], "name": added["name"]})
            return {}
        m = re.fullmatch(r"/task/([^/]+)", path)
        if method == "PUT" and m and m.group(1) in self.tasks:
            return self._task_view(self._update_task(self.tasks[m.group(1)], body), markdown=False)
        m = re.fullmatch(r"/task/([^/]+)/tag/([^/]+)", path)
        if m and m.group(1) in self.tasks:  # POST puts the tag on, and the one DELETE takes it off
            rec, name = self.tasks[m.group(1)], urllib.parse.unquote(m.group(2)).lower()
            rec["tags"] = [t for t in rec["tags"] if t["name"] != name]
            if method == "POST":
                rec["tags"].append({"name": name, "tag_fg": "", "tag_bg": "", "creator": U_ROBIN})
            return {}
        m = re.fullmatch(r"/task/([^/]+)/comment", path)
        if method == "POST" and m and m.group(1) in self.tasks:
            made = {"id": str(next(self._ids)), "hist_id": f"hist-{len(self.comments) + 1}", "date": int(ms(COMMENTED)),
                    "task": m.group(1), **body}
            self.comments.append(made)
            return {k: made[k] for k in ("id", "hist_id", "date")}
        if method == "POST" and path == f"/space/{SPACE}/tag":
            tag = body["tag"]
            if not (tag.get("name") and tag.get("tag_fg") and tag.get("tag_bg")):
                raise ValidationError("HTTP 400: a tag needs its name and both colours")
            if tag["name"].lower() not in self.tags:
                self.tags.append(tag["name"].lower())
            return {}
        raise NotFound(f"fake has no route for {method} {path}")

    # -- views -------------------------------------------------------------------------

    def _list_view(self, rec: dict[str, Any], *, embedded: bool = False) -> dict[str, Any]:
        out = copy.deepcopy(rec)
        out["task_count"] = sum(1 for t in self.tasks.values() if not t["parent"]
                                and (t["list"]["id"] == rec["id"] or any(x["id"] == rec["id"] for x in t["locations"])))
        if not embedded:
            out["statuses"] = copy.deepcopy(self.statuses)
        return out

    def _folder_view(self, folder_id: str) -> dict[str, Any]:
        inside = [self._list_view(x, embedded=True) for x in self.lists.values()
                  if x["folder"]["id"] == folder_id and not x["archived"]]
        return {"id": folder_id, "name": self.folders[folder_id], "archived": False, "hidden": False,
                "override_statuses": False, "space": {"id": SPACE}, "task_count": str(sum(x["task_count"] for x in inside)),
                "statuses": copy.deepcopy(self.statuses), "lists": inside}

    def _task_page(self, found: list[dict[str, Any]], p: dict[str, Any], *, markdown: bool) -> dict[str, Any]:
        for rule in json.loads(p.get("custom_fields") or "[]"):
            if rule["operator"] != "==":
                raise ValidationError(f"the fake filters a text field by == alone, not {rule['operator']!r}")
            found = [t for t in found if any(f["id"] == rule["field_id"] and f.get("value") == rule["value"]
                                             for f in t["custom_fields"])]
        if p.get("subtasks") != "true":
            found = [t for t in found if not t["parent"]]
        if p.get("include_closed") != "true":
            found = [t for t in found if t["status"]["type"] != "closed"]
        for tag in p.get("tags[]") or []:  # exact, as the probe read it
            found = [t for t in found if any(x["name"] == tag for x in t["tags"])]
        page = int(p.get("page") or 0)
        cut = found[page * self.page_size:(page + 1) * self.page_size]
        return {"tasks": [self._task_view(t, markdown=markdown) for t in cut],
                "last_page": (page + 1) * self.page_size >= len(found)}

    @staticmethod
    def _task_view(rec: dict[str, Any], *, markdown: bool) -> dict[str, Any]:
        out = copy.deepcopy(rec)
        if markdown:
            out["markdown_description"] = rec["description"] + ("\n" if rec["description"] else "")
        return out

    # -- the transport surface ------------------------------------------------------------

    def request(self, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
        self.calls.append((method, path, params, body))
        key = f"{method} {path}"
        if key in self.fail:
            raise self.fail[key]
        p = params or {}
        if not allowed(method, path):  # as the real transport: no DELETE but a tag coming off a task
            raise Unsupported(f"the ClickUp transport sends no {method} to {path}")
        if method != "GET":
            return self._write(method, path, body)
        if path == "/user":
            return {"user": dict(self.user)}
        if path == "/team":
            return {"teams": [{"id": WS, "name": "Workspace", "members": [{"user": dict(m)} for m in self.members]},
                              {"id": "9002", "name": "Another", "members": []}]}
        if path == f"/team/{WS}/custom_item":
            return {"custom_items": copy.deepcopy(self.custom_items)}
        if path == f"/space/{SPACE}":
            return {**copy.deepcopy(self.space), "statuses": copy.deepcopy(self.statuses)}
        if path == f"/space/{SPACE}/tag":
            return {"tags": [{"name": t, "tag_fg": "", "tag_bg": "", "creator": U_ROBIN, "project_id": SPACE} for t in self.tags]}
        if path == f"/space/{SPACE}/folder":
            return {"folders": [self._folder_view(f) for f in self.folders]}
        if path == f"/space/{SPACE}/list":
            return {"lists": [self._list_view(x) for x in self.lists.values() if x["folder"]["id"] == "0" and not x["archived"]]}
        if path == f"/team/{WS}/task":
            wanted = set(p.get("list_ids[]") or [])
            found = [t for t in self.tasks.values() if t["list"]["id"] in wanted]  # never a task that was only added
            return self._task_page(found, p, markdown=False)
        m = re.fullmatch(r"/folder/(\d+)/list", path)
        if m and m.group(1) in self.folders:
            archived = p.get("archived") == "true"
            return {"lists": [self._list_view(x) for x in self.lists.values()
                              if x["folder"]["id"] == m.group(1) and x["archived"] is archived]}
        m = re.fullmatch(r"/folder/(\d+)", path)
        if m and m.group(1) in self.folders:
            return self._folder_view(m.group(1))
        m = re.fullmatch(r"/list/(\d+)/task", path)
        if m and m.group(1) in self.lists:
            lid = m.group(1)
            found = [t for t in self.tasks.values() if t["list"]["id"] == lid
                     or (p.get("include_timl") == "true" and any(x["id"] == lid for x in t["locations"]))]
            return self._task_page(found, p, markdown=p.get("include_markdown_description") == "true")
        m = re.fullmatch(r"/list/(\d+)/field", path)
        if m and m.group(1) in self.lists:
            return {"fields": copy.deepcopy(self.fields)}
        m = re.fullmatch(r"/list/(\d+)", path)
        if m and m.group(1) in self.lists:
            return self._list_view(self.lists[m.group(1)])
        m = re.fullmatch(r"/task/([^/]+)", path)
        if m:
            ident = m.group(1)
            by_key = p.get("custom_task_ids") == "true" and str(p.get("team_id")) == WS
            hit = next((t for t in self.tasks.values() if (t["custom_id"] == ident if by_key else t["id"] == ident)), None)
            if hit is None:
                raise NotFound(f"HTTP 404 on {key}: no such task")
            return self._task_view(hit, markdown=p.get("include_markdown_description") == "true")
        raise NotFound(f"fake has no route for {key}")

    def get_all(self, path: str, params: dict | None = None) -> list[Any]:
        from adapters.clickup.transport import rows

        params = dict(params or {})
        items: list[Any] = []
        while True:
            body = self.request("GET", path, params=dict(params))
            found = rows(body)
            items.extend(found)
            if "last_page" not in body or body["last_page"] or not found:
                return items
            params["page"] = int(params.get("page") or 0) + 1
