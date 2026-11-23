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
"""

from __future__ import annotations

import copy
import itertools
import re
from typing import Any

from adapters.base import NotFound

WS, SPACE, OTHER_SPACE = "9001", "9101", "9102"
F_WORK, F_SPRINTS = "9201", "9202"
L_INBOX, L_WEB, L_ELSEWHERE = "9301", "9302", "9399"
T_MILESTONE, T_EPIC, T_STORY, T_BUG = 1, 1001, 1002, 1003
U_ROBIN = 9501

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
                 space: str = SPACE) -> dict[str, Any]:
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
        }
        self.tasks[tid] = rec
        return rec

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
        if method != "GET":
            raise NotFound(f"fake has no route for {key}")
        if path == "/user":
            return {"user": dict(self.user)}
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
