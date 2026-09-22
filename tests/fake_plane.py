"""A fake Plane transport for the offline tests — never a live tracker.

Shapes follow the Phase 1 probe (probes/plane_phase1_readonly.py): the
project record, per-project `work-item-types` / `states/` / `labels/` /
`modules/` / `cycles/`, workspace `members-lite`, the cursor envelope on
`work-items`, the `issues`-keyed search envelope. Ids are made up.
"""

from __future__ import annotations

import copy
import itertools
import re
from typing import Any

from adapters.base import NotFound, ValidationError

WS = "/workspaces/ws"
PID = "11111111-1111-1111-1111-111111111111"
PP = f"{WS}/projects/{PID}"

T_EPIC = "aaaaaaaa-0000-0000-0000-00000000e91c"
T_STORY = "aaaaaaaa-0000-0000-0000-0000000570e1"
T_TASK = "aaaaaaaa-0000-0000-0000-000000007a5c"
T_BUG = "aaaaaaaa-0000-0000-0000-000000000b06"

S_BACKLOG = "bbbbbbbb-0000-0000-0000-000000000001"
S_TODO = "bbbbbbbb-0000-0000-0000-000000000002"
S_PROGRESS = "bbbbbbbb-0000-0000-0000-000000000003"
S_DONE = "bbbbbbbb-0000-0000-0000-000000000004"
S_CANCELLED = "bbbbbbbb-0000-0000-0000-000000000005"

L_REVIEW = "cccccccc-0000-0000-0000-000000000001"
L_BUG = "cccccccc-0000-0000-0000-000000000002"
L_FEATURE = "cccccccc-0000-0000-0000-000000000003"
L_INIT = "cccccccc-0000-0000-0000-000000000004"

M_INTAKE = "dddddddd-0000-0000-0000-000000000001"
M_ADAPTER = "dddddddd-0000-0000-0000-000000000002"

C_202609 = "eeeeeeee-0000-0000-0000-000000000009"
C_202608 = "eeeeeeee-0000-0000-0000-000000000008"

U_CHRIS = "ffffffff-0000-0000-0000-000000000001"

I_EPIC = "12121212-0000-0000-0000-000000000001"
I_STORY = "12121212-0000-0000-0000-000000000002"


def project() -> dict[str, Any]:
    return {"id": PID, "name": "agentic_administration", "identifier": "AA",
            "cycle_view": True, "module_view": True, "archived_at": None}


def base_routes(*, with_bug: bool = False) -> dict[str, Any]:
    types = [
        {"id": T_EPIC, "name": "Epic", "level": 1, "is_epic": True, "is_default": False},
        {"id": T_STORY, "name": "Story", "level": 0, "is_epic": False, "is_default": False},
        {"id": T_TASK, "name": "Task", "level": 0, "is_epic": False, "is_default": True},
    ]
    if with_bug:
        types.append({"id": T_BUG, "name": "Bug", "level": 0, "is_epic": False, "is_default": False})
    return {
        f"GET {WS}/projects/": {"results": [project()], "next_cursor": "", "next_page_results": False},
        f"GET {PP}/features": {"epics": True, "modules": True, "cycles": True, "work_item_types": True},
        f"GET {PP}/work-item-types": types,
        f"GET {PP}/states/": [
            {"id": S_BACKLOG, "name": "Backlog", "group": "backlog"},
            {"id": S_TODO, "name": "Todo", "group": "unstarted"},
            {"id": S_PROGRESS, "name": "In Progress", "group": "started"},
            {"id": S_DONE, "name": "Done", "group": "completed"},
            {"id": S_CANCELLED, "name": "Cancelled", "group": "cancelled"},
        ],
        f"GET {PP}/labels/": [
            {"id": L_REVIEW, "name": "needs-review"},
            {"id": L_BUG, "name": "bug"},
            {"id": L_FEATURE, "name": "feature"},
            {"id": L_INIT, "name": "initiative:INIT-1"},
        ],
        f"GET {WS}/members-lite": [
            {"id": U_CHRIS, "display_name": "chris", "email": "chris@example.invalid", "role": 20},
        ],
        f"GET {PP}/modules/": [
            {"id": M_INTAKE, "name": "Intake"},
            {"id": M_ADAPTER, "name": "Adapter"},
        ],
        f"GET {PP}/cycles/": [
            {"id": C_202608, "name": "202608", "start_date": "2026-08-01", "end_date": "2026-08-31", "status": "completed"},
            {"id": C_202609, "name": "202609", "start_date": "2026-09-01", "end_date": "2026-09-30", "status": "current"},
        ],
        f"GET {PP}/work-items": {
            "results": [item_record(I_EPIC, 1, "Requester Intake", T_EPIC),
                        item_record(I_STORY, 2, "Requester Can File A Bug", T_STORY, parent=I_EPIC,
                                    state=S_TODO, labels=[L_REVIEW], cycle_id=C_202609,
                                    min_module_name="Intake", external_id="req-0001")],
            "next_cursor": "", "next_page_results": False, "total_count": 2,
        },
        f"GET {WS}/work-items/search": {"issues": []},
    }


def item_record(iid: str, seq: int, name: str, type_id: str, **extra: Any) -> dict[str, Any]:
    rec = {
        "id": iid, "sequence_id": seq, "name": name, "type_id": type_id, "project_id": PID,
        "state": S_BACKLOG, "parent": None, "labels": [], "assignees": [], "cycle_id": None,
        "min_module_name": None, "external_id": None, "external_source": None,
        "description_html": "<p></p>", "description_stripped": "",
    }
    rec.update(extra)
    return rec


class FakeTransport:
    """Route table + a log of every call. Writes create records so a
    create → read round-trip works; unknown routes raise `NotFound`."""

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.routes = copy.deepcopy(routes if routes is not None else base_routes())
        self.calls: list[tuple[str, str, dict | None, Any]] = []
        self._seq = itertools.count(100)
        self._ids = itertools.count(1)
        self.fail: dict[str, Exception] = {}  # "METHOD path" -> raise

    def new_id(self, prefix: str = "99999999") -> str:
        return f"{prefix}-0000-0000-0000-{next(self._ids):012d}"

    def request(self, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
        self.calls.append((method, path, params, body))
        key = f"{method} {path}"
        if key in self.fail:
            raise self.fail[key]
        if key in self.routes:
            value = self.routes[key]
            return value(params, body) if callable(value) else copy.deepcopy(value)
        if method == "GET":
            m = re.fullmatch(rf"{re.escape(PP)}/work-items/([0-9a-f-]+)", path)
            if m:
                for r in self.routes[f"GET {PP}/work-items"]["results"]:
                    if r["id"] == m.group(1):
                        return copy.deepcopy(r)
            m = re.fullmatch(rf"{re.escape(WS)}/work-items/AA-(\d+)", path)
            if m:
                for r in self.routes[f"GET {PP}/work-items"]["results"]:
                    if r["sequence_id"] == int(m.group(1)):
                        return copy.deepcopy(r)
            m = re.fullmatch(rf"{re.escape(PP)}/cycles/([0-9a-f-]+)/", path)
            if m:
                for c in self.routes[f"GET {PP}/cycles/"]:
                    if c["id"] == m.group(1):
                        return copy.deepcopy(c)
            raise NotFound(f"HTTP 404 on {key}")
        if method == "POST" and path == f"{PP}/work-items/":
            if not (body or {}).get("name"):
                raise ValidationError("HTTP 400 on POST work-items: name: This field is required.")
            rec = item_record(self.new_id(), next(self._seq), body["name"], body.get("type_id"))
            rec.update({k: v for k, v in body.items() if k not in ("name", "type_id")})
            self.routes[f"GET {PP}/work-items"]["results"].append(rec)
            return copy.deepcopy(rec)
        m = re.fullmatch(rf"{re.escape(PP)}/work-items/([0-9a-f-]+)/", path)
        if method == "PATCH" and m:
            for r in self.routes[f"GET {PP}/work-items"]["results"]:
                if r["id"] == m.group(1):
                    r.update(body or {})
                    return copy.deepcopy(r)
            raise NotFound(f"HTTP 404 on {key}")
        if method == "POST" and re.fullmatch(rf"{re.escape(PP)}/work-items/[0-9a-f-]+/comments/", path):
            return {"id": self.new_id("c0c0c0c0"), "actor": U_CHRIS, "created_at": "2026-09-22T10:00:00Z", **(body or {})}
        if method == "POST" and re.fullmatch(rf"{re.escape(PP)}/(modules|cycles)/[0-9a-f-]+/(module|cycle)-issues/", path):
            return {}
        if method == "POST" and path == f"{PP}/modules/":
            rec = {"id": self.new_id("d0d0d0d0"), **(body or {})}
            self.routes[f"GET {PP}/modules/"].append(rec)
            return copy.deepcopy(rec)
        if method == "POST" and path == f"{PP}/cycles/":
            rec = {"id": self.new_id("e0e0e0e0"), "status": "upcoming", **(body or {})}
            self.routes[f"GET {PP}/cycles/"].append(rec)
            return copy.deepcopy(rec)
        m = re.fullmatch(rf"{re.escape(PP)}/cycles/([0-9a-f-]+)/", path)
        if method == "PATCH" and m:
            for c in self.routes[f"GET {PP}/cycles/"]:
                if c["id"] == m.group(1):
                    c.update(body or {})
                    if c.get("end_date", "9999") < "2026-09-22":
                        c["status"] = "completed"
                    return copy.deepcopy(c)
        if method == "POST" and path == f"{PP}/work-item-types":
            rec = {"id": T_BUG, "name": (body or {}).get("name"), "is_epic": False, "level": 0}
            self.routes[f"GET {PP}/work-item-types"].append(rec)
            return copy.deepcopy(rec)
        raise NotFound(f"fake has no route for {key}")

    def get_all(self, path: str, params: dict | None = None) -> list[Any]:
        page = self.request("GET", path, params=params)
        if isinstance(page, list):
            return page
        return list(page.get("results") or [])

    def bodies(self, method: str, path_fragment: str) -> list[Any]:
        return [b for m, p, _, b in self.calls if m == method and path_fragment in p]
