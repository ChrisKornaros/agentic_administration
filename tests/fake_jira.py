"""A fake Jira Cloud transport for the offline tests — never a live tracker.

Shapes follow the Phase 5 probe (probes/jira_phase5_readonly.py, run
2026-09-27 against a company-managed Scrum project): the project with its
`issueTypes` and their hierarchy levels, `statuses` per type with a
category, the `values` envelope on labels and sprints, the bare lists of
users and components, the `/search/jql` page with `isLast` and a
`nextPageToken`, the global transitions named after their target status.
The rules it enforces are Jira's, as the 2026-09-27 conformance run met
them: a parent sits at a higher hierarchy level than its child, not
necessarily the adjacent one (live Jira took a sub-task straight under an
epic); labels hold no spaces; a sprint starts only from future with both
dates and while no other is active, closes only from active, and takes no
issues once closed. From the Phase 6 rollover run (2026-09-27): an issue
moved out of a closed sprint keeps it in its Sprint field, which JQL
`sprint =` still matches, and a moved issue's sub-tasks come along, done
ones too. Ids are made up.
"""

from __future__ import annotations

import copy
import itertools
import re
from datetime import datetime, timezone
from typing import Any

from adapters.base import NotFound, ValidationError

KEY, PID, BOARD = "AA", "10001", "2"
T_EPIC, T_STORY, T_SUB, T_BUG, T_TASK = "10000", "10005", "10008", "10009", "10010"
S_BACKLOG, S_TODO, S_PROGRESS, S_CANCELLED, S_DONE = "10004", "10005", "3", "10006", "10007"
SPRINT_FIELD = "customfield_10020"
U_CHRIS = "acc-chris"
C_INTAKE = "10100"

_TYPES = [
    {"id": T_SUB, "name": "Sub-task", "hierarchyLevel": -1, "subtask": True},
    {"id": T_EPIC, "name": "Epic", "hierarchyLevel": 1, "subtask": False},
    {"id": T_STORY, "name": "Story", "hierarchyLevel": 0, "subtask": False},
    {"id": T_BUG, "name": "Bug", "hierarchyLevel": 0, "subtask": False},
    {"id": T_TASK, "name": "Task", "hierarchyLevel": 0, "subtask": False},
]
_STATUSES = [
    {"id": S_BACKLOG, "name": "Backlog", "statusCategory": {"key": "new"}},
    {"id": S_TODO, "name": "To Do", "statusCategory": {"key": "new"}},
    {"id": S_PROGRESS, "name": "In Progress", "statusCategory": {"key": "indeterminate"}},
    {"id": S_CANCELLED, "name": "Cancelled", "statusCategory": {"key": "done"}},
    {"id": S_DONE, "name": "Done", "statusCategory": {"key": "done"}},
]


def _utc(value: str | None) -> str | None:
    """Jira answers sprint instants in UTC, whatever offset they were written at."""
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FakeJira:
    """In-memory project + board + a log of every call. Unknown routes raise `NotFound`."""

    def __init__(self, *, board_type: str = "scrum", with_sub_task: bool = True) -> None:
        types = [t for t in _TYPES if with_sub_task or t["id"] != T_SUB]
        self.project = {"id": PID, "key": KEY, "name": "Agentic Admin", "style": "classic", "simplified": False,
                        "issueTypes": types}
        self.statuses = copy.deepcopy(_STATUSES)
        self.site_labels = ["bug", "docs"]
        self.users = [{"accountId": U_CHRIS, "accountType": "atlassian", "displayName": "Chris",
                       "emailAddress": "chris@example.invalid", "active": True},
                      {"accountId": "app-1", "accountType": "app", "displayName": "Automation", "active": True}]
        self.components = [{"id": C_INTAKE, "name": "Intake"}]
        self.fields = [{"id": "summary", "custom": False, "schema": {"type": "string"}},
                       {"id": SPRINT_FIELD, "name": "Sprint", "custom": True,
                        "schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}}]
        self.me = {"accountId": U_CHRIS, "timeZone": "America/New_York"}
        self.board = {"id": int(BOARD), "name": "AA board", "type": board_type, "location": {"projectKey": KEY}}
        self.sprints: dict[str, dict[str, Any]] = {}
        self.issues: dict[str, dict[str, Any]] = {}
        self.hidden: set[str] = set()  # issue ids the search has not indexed yet
        self.calls: list[tuple[str, str, dict | None, Any]] = []
        self.fail: dict[str, Exception] = {}  # "METHOD path" -> raise
        self._ids = itertools.count(10200)
        self._keys = itertools.count(1)

    # -- helpers -----------------------------------------------------------------

    @property
    def log(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _, _ in self.calls]

    def bodies(self, method: str, path_fragment: str) -> list[Any]:
        return [b for m, p, _, b in self.calls if m == method and path_fragment in p]

    def _type(self, tid: str) -> dict[str, Any]:
        hit = next((t for t in self.project["issueTypes"] if t["id"] == tid), None)
        if hit is None:
            raise ValidationError(f"HTTP 400 on POST /rest/api/3/issue: issuetype: Specify a valid work type")
        return hit

    def _status(self, sid: str) -> dict[str, Any]:
        return next(s for s in self.statuses if s["id"] == sid)

    def _find(self, ident: str) -> dict[str, Any]:
        for rec in self.issues.values():
            if ident in (rec["id"], rec["key"]):
                return rec
        raise NotFound(f"HTTP 404 on GET /rest/api/3/issue/{ident}: Issue does not exist or you do not have permission to see it.")

    def _view(self, rec: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(rec)
        if out["fields"].get(SPRINT_FIELD):  # each sprint as it is now, as live Jira renders the field
            out["fields"][SPRINT_FIELD] = [copy.deepcopy(self.sprints.get(str(s["id"]), s))
                                           for s in out["fields"][SPRINT_FIELD]]
        parent_id = out["fields"].pop("_parent", None)
        if parent_id:
            p = self.issues[parent_id]
            out["fields"]["parent"] = {"id": p["id"], "key": p["key"], "fields": {
                "summary": p["fields"]["summary"], "status": copy.deepcopy(p["fields"]["status"]),
                "issuetype": copy.deepcopy(p["fields"]["issuetype"])}}
        return out

    def add_issue(self, type_id: str, summary: str, **fields: Any) -> dict[str, Any]:
        """Seed an issue directly (no call logged)."""
        iid, key = str(next(self._ids)), f"{KEY}-{next(self._keys)}"
        rec = {"id": iid, "key": key, "fields": {
            "summary": summary, "issuetype": copy.deepcopy(self._type(type_id)), "status": self._status(S_BACKLOG),
            "labels": [], "assignee": None, "components": [], "description": None, SPRINT_FIELD: None,
            "created": "2026-09-27T10:00:00.000+0000", "_parent": None}}
        rec["fields"].update(fields)
        self.issues[iid] = rec
        return rec

    def add_sprint(self, name: str, state: str = "future", start: str | None = None, end: str | None = None) -> dict[str, Any]:
        sid = str(next(self._ids))
        rec = {"id": int(sid), "name": name, "state": state, "startDate": _utc(start), "endDate": _utc(end),
               "originBoardId": int(BOARD)}
        self.sprints[sid] = rec
        return rec

    # -- search ----------------------------------------------------------------

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        jql = params.get("jql") or ""
        where = re.split(r"\s+ORDER BY\s+", jql)[0]
        rows = [r for r in self.issues.values() if r["id"] not in self.hidden]
        for clause in where.split(" AND "):
            m = re.fullmatch(r'(\w+)\s*(=|~)\s*(?:"((?:[^"\\]|\\.)*)"|(\S+))', clause.strip())
            if not m:
                raise ValidationError(f"HTTP 400 on GET /rest/api/3/search/jql: Error in the JQL Query: {clause!r}")
            name, op, quoted, bare = m.groups()
            value = re.sub(r"\\(.)", r"\1", quoted) if quoted is not None else bare
            if (name, op) == ("project", "="):
                rows = [r for r in rows if value == KEY]
            elif (name, op) == ("labels", "="):
                rows = [r for r in rows if value in r["fields"]["labels"]]
            elif (name, op) == ("text", "~"):
                words = value.lower().split()
                rows = [r for r in rows if all(w in r["fields"]["summary"].lower() for w in words)]
            elif (name, op) == ("issuetype", "="):
                rows = [r for r in rows if r["fields"]["issuetype"]["id"] == value]
            elif (name, op) == ("status", "="):
                rows = [r for r in rows if r["fields"]["status"]["id"] == value]
            elif (name, op) == ("sprint", "="):  # any sprint in the field, closed history included
                rows = [r for r in rows if any(str(s["id"]) == value for s in r["fields"].get(SPRINT_FIELD) or [])]
            else:
                raise ValidationError(f"HTTP 400 on GET /rest/api/3/search/jql: the fake does not know {clause!r}")
        rows.sort(key=lambda r: int(r["id"]), reverse=True)
        start = int(params.get("nextPageToken") or 0)
        size = int(params.get("maxResults") or 50)
        page = rows[start : start + size]
        out: dict[str, Any] = {"issues": [self._view(r) for r in page], "isLast": start + size >= len(rows)}
        if not out["isLast"]:
            out["nextPageToken"] = str(start + size)
        return out

    # -- writes --------------------------------------------------------------------

    def _create(self, body: dict[str, Any]) -> dict[str, Any]:
        f = dict((body or {}).get("fields") or {})
        where = "POST /rest/api/3/issue"
        if not f.get("summary"):
            raise ValidationError(f"HTTP 400 on {where}: summary: You must specify a summary of the issue.")
        itype = self._type((f.get("issuetype") or {}).get("id") or "")
        for label in f.get("labels") or []:
            if re.search(r"\s", label):
                raise ValidationError(f"HTTP 400 on {where}: labels: The label '{label}' contains spaces which is invalid.")
        parent_id = None
        if f.get("parent"):
            parent = self._find(f["parent"].get("id") or f["parent"].get("key"))
            if parent["fields"]["issuetype"]["hierarchyLevel"] <= itype["hierarchyLevel"]:
                raise ValidationError(f"HTTP 400 on {where}: parent: Given parent work item does not belong to appropriate hierarchy.")
            parent_id = parent["id"]
        elif itype["subtask"]:
            raise ValidationError(f"HTTP 400 on {where}: parent: Parent is required for sub-tasks.")
        sprint = None
        if f.get(SPRINT_FIELD) is not None:
            sprint = self.sprints.get(str(f[SPRINT_FIELD]))
            if sprint is None or sprint["state"] == "closed":
                raise ValidationError(f"HTTP 400 on {where}: {SPRINT_FIELD}: Sprint is not valid")
        component_ids = [c["id"] for c in f.get("components") or []]
        rec = self.add_issue(
            itype["id"], f["summary"], labels=list(f.get("labels") or []), description=f.get("description"),
            assignee=next(({"accountId": u["accountId"], "displayName": u["displayName"]} for u in self.users
                           if u["accountId"] == (f.get("assignee") or {}).get("accountId")), None),
            components=[c for c in self.components if c["id"] in component_ids],
            _parent=parent_id,
        )
        if sprint is not None:
            rec["fields"][SPRINT_FIELD] = [copy.deepcopy(sprint)]
        return {"id": rec["id"], "key": rec["key"], "self": f"https://example.invalid/rest/api/3/issue/{rec['id']}"}

    def _update(self, rec: dict[str, Any], body: dict[str, Any]) -> None:
        f = (body or {}).get("fields") or {}
        for label in f.get("labels") or []:
            if re.search(r"\s", label):
                raise ValidationError(f"HTTP 400 on PUT: labels: The label '{label}' contains spaces which is invalid.")
        for name in ("summary", "description", "labels"):
            if name in f:
                rec["fields"][name] = f[name]
        if "assignee" in f:
            who = (f["assignee"] or {}).get("accountId")
            rec["fields"]["assignee"] = next(({"accountId": u["accountId"], "displayName": u["displayName"]}
                                              for u in self.users if u["accountId"] == who), None)
        if "parent" in f:
            rec["fields"]["_parent"] = self._find(f["parent"].get("id") or f["parent"].get("key"))["id"]

    def _sprint_update(self, sid: str, body: dict[str, Any]) -> dict[str, Any]:
        s = self.sprints.get(sid)
        if s is None:
            raise NotFound(f"HTTP 404 on POST /rest/agile/1.0/sprint/{sid}")
        where = f"POST /rest/agile/1.0/sprint/{sid}"
        state = (body or {}).get("state")
        if state == "active":
            if s["state"] != "future" or not (s["startDate"] and s["endDate"]):
                raise ValidationError(f"HTTP 400 on {where}: Sprint must be in the future state with dates to start")
            if any(o["state"] == "active" for o in self.sprints.values()):
                raise ValidationError(f"HTTP 400 on {where}: Another sprint is already active on this board")
            s["state"] = "active"
        elif state == "closed":
            if s["state"] != "active":
                raise ValidationError(f"HTTP 400 on {where}: Only an active sprint can be closed")
            s["state"], s["completeDate"] = "closed", "2026-09-27T12:00:00.000Z"
        return copy.deepcopy(s)

    def _move(self, sid: str, body: dict[str, Any]) -> None:
        s = self.sprints.get(sid)
        if s is None:
            raise NotFound(f"HTTP 404 on POST /rest/agile/1.0/sprint/{sid}/issue")
        if s["state"] == "closed":  # live Jira's words, 2026-09-27
            raise ValidationError(f"HTTP 400 on POST /rest/agile/1.0/sprint/{sid}/issue: "
                                  "You must specify a sprint which has not been completed.")
        for ident in (body or {}).get("issues") or []:
            rec = self._find(ident)
            # its sub-tasks come along, done ones too (live, 2026-09-27: AGADM-4 followed AGADM-2)
            subs = [r for r in self.issues.values() if r["fields"].get("_parent") == rec["id"]
                    and r["fields"]["issuetype"]["subtask"]]
            for r in [rec, *subs]:
                # the field keeps the closed sprints an issue was carried out of; an open one it leaves drops out
                history = [x for x in r["fields"].get(SPRINT_FIELD) or []
                           if self.sprints.get(str(x["id"]), x)["state"] == "closed" and str(x["id"]) != sid]
                r["fields"][SPRINT_FIELD] = history + [copy.deepcopy(s)]

    # -- the transport surface ------------------------------------------------------

    def request(self, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
        self.calls.append((method, path, params, body))
        key = f"{method} {path}"
        if key in self.fail:
            raise self.fail[key]
        p = params or {}
        if method == "GET":
            if path == f"/rest/api/3/project/{KEY}":
                return copy.deepcopy(self.project)
            if path == f"/rest/api/3/project/{KEY}/statuses":
                return [{"id": t["id"], "name": t["name"], "statuses": copy.deepcopy(self.statuses)}
                        for t in self.project["issueTypes"]]
            if path == "/rest/api/3/label":
                used = {l for r in self.issues.values() for l in r["fields"]["labels"]}
                values = sorted(set(self.site_labels) | used)
                return {"startAt": 0, "maxResults": 1000, "total": len(values), "isLast": True, "values": values}
            if path == "/rest/api/3/user/assignable/search":
                return copy.deepcopy(self.users)
            if path == f"/rest/api/3/project/{KEY}/components":
                return copy.deepcopy(self.components)
            if path == "/rest/api/3/field":
                return copy.deepcopy(self.fields)
            if path == "/rest/api/3/myself":
                return dict(self.me)
            if path == f"/rest/agile/1.0/board/{BOARD}":
                return copy.deepcopy(self.board)
            if path == f"/rest/agile/1.0/board/{BOARD}/sprint":
                if self.board["type"] != "scrum":
                    raise ValidationError(f"HTTP 400 on {key}: The board does not support sprints")
                return {"startAt": 0, "maxResults": 50, "isLast": True, "values": copy.deepcopy(list(self.sprints.values()))}
            if path == "/rest/api/3/search/jql":
                return self._search(p)
            m = re.fullmatch(r"/rest/agile/1.0/sprint/(\d+)", path)
            if m:
                if m.group(1) not in self.sprints:
                    raise NotFound(f"HTTP 404 on {key}: Sprint does not exist")
                return copy.deepcopy(self.sprints[m.group(1)])
            m = re.fullmatch(r"/rest/api/3/issue/([^/]+)/transitions", path)
            if m:
                self._find(m.group(1))
                return {"transitions": [{"id": f"t{s['id']}", "name": s["name"], "hasScreen": False, "isGlobal": True,
                                         "to": copy.deepcopy(s)} for s in self.statuses]}
            m = re.fullmatch(r"/rest/api/3/issue/([^/]+)", path)
            if m:
                return self._view(self._find(m.group(1)))
        if method == "POST":
            if path == "/rest/api/3/issue":
                return self._create(body)
            if path == "/rest/agile/1.0/sprint":
                b = body or {}
                if str(b.get("originBoardId")) != BOARD:
                    raise ValidationError(f"HTTP 400 on {key}: originBoardId: board not found")
                return copy.deepcopy(self.add_sprint(b["name"], start=b.get("startDate"), end=b.get("endDate")))
            m = re.fullmatch(r"/rest/agile/1.0/sprint/(\d+)/issue", path)
            if m:
                return self._move(m.group(1), body)
            m = re.fullmatch(r"/rest/agile/1.0/sprint/(\d+)", path)
            if m:
                return self._sprint_update(m.group(1), body)
            m = re.fullmatch(r"/rest/api/3/issue/([^/]+)/transitions", path)
            if m:
                rec = self._find(m.group(1))
                tid = ((body or {}).get("transition") or {}).get("id") or ""
                rec["fields"]["status"] = self._status(tid.removeprefix("t"))
                return None
            m = re.fullmatch(r"/rest/api/3/issue/([^/]+)/comment", path)
            if m:
                self._find(m.group(1))
                return {"id": str(next(self._ids)), "author": {"accountId": U_CHRIS, "displayName": "Chris"},
                        "created": "2026-09-27T12:00:00.000+0000", "body": (body or {}).get("body")}
        if method == "PUT":
            m = re.fullmatch(r"/rest/api/3/issue/([^/]+)", path)
            if m:
                self._update(self._find(m.group(1)), body)
                return None
        raise NotFound(f"fake has no route for {key}")

    def get_all(self, path: str, params: dict | None = None) -> list[Any]:
        page = self.request("GET", path, params=params)
        if isinstance(page, list):
            return page
        return list(page.get("values") or [])
