"""Phase 1 — read-only probe of the Plane Cloud v1 API (run 2026-09-16).

The live check that gated the Plane adapter: do the pre-May-2026 routes
(`issues/`, `issue-types/`) still answer next to `work-items` /
`work-item-types`; which Work Item Types exist per project; is there any
read surface for the Hierarchy feature; is `external_id` on the records and
accepted by search; what do `features`, `members-lite`, `initiatives`,
retrieve-by-identifier and `expand=` return. Findings are recorded in the
design repo (agentic_optimization_research: roadmap/14 §3.1 and
tools/plane/API.md); this file is the evidence of *how* they were read.

Every call is a GET — nothing is written. It borrows the seed CLI's secret
boundary (`plane.py`: `_load_dotenv` + `_resolve_secrets`, token from
Bitwarden via `BW_SESSION`) and its `USER_AGENT` / `API_BASE`, but does its
own urllib so non-2xx answers are recorded instead of exiting. Throttled
~1.5 s/call (the API limits at ~60/min). Stdlib only.

Usage:
  PLANE_CLI_DIR=<dir containing plane.py + .env>   # default: the sibling AOR checkout
  uv run --no-project probes/plane_phase1_readonly.py --plan   # call list, no network
  BW_SESSION='...' uv run --no-project probes/plane_phase1_readonly.py
  # writes probe-report.json next to this file (board content — gitignored)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
_DEFAULT_CLI_DIR = HERE.parents[1] / "agentic_optimization_research" / "tools" / "plane"
sys.path.insert(0, os.environ.get("PLANE_CLI_DIR") or str(_DEFAULT_CLI_DIR))
import plane  # noqa: E402  (the seed CLI; see module docstring)
THROTTLE = 1.5
DEEP_PROJECTS = 3          # projects that get the full per-project probe set
PREFER = ("agentic", "AOR")  # pick these boards first if present
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

log: list[dict] = []


def get(label: str, path: str, params: dict | None = None) -> tuple[int, object]:
    """GET API_BASE+path; record (status, parsed body or text) and return it."""
    url = f"{plane.API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {
        "X-API-Key": os.environ["PLANE_API_KEY"],
        "Accept": "application/json",
        "User-Agent": plane.USER_AGENT,
    }
    req = urllib.request.Request(url, method="GET", headers=headers)
    status, body = 0, None
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        status, raw = -1, str(exc.reason)
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = raw[:400]  # e.g. a Cloudflare HTML page
    shape = summarize(body)
    log.append({"label": label, "path": path, "params": params, "status": status, "shape": shape})
    print(f"{status:>4}  {label:<34} {path}{'?' + urllib.parse.urlencode(params) if params else ''}", flush=True)
    time.sleep(THROTTLE)
    return status, body


def summarize(body: object) -> object:
    """Shape of a response: keys of a dict / first element; never full content."""
    if isinstance(body, dict):
        if "results" in body and isinstance(body["results"], list):
            first = body["results"][0] if body["results"] else None
            return {"envelope": sorted(k for k in body if k != "results"),
                    "count": len(body["results"]), "total_count": body.get("total_count"),
                    "item_keys": sorted(first) if isinstance(first, dict) else None}
        return {"keys": sorted(body)}
    if isinstance(body, list):
        first = body[0] if body else None
        return {"list_len": len(body), "item_keys": sorted(first) if isinstance(first, dict) else None}
    return body


def rows(body: object) -> list:
    if isinstance(body, dict) and isinstance(body.get("results"), list):
        return body["results"]
    return body if isinstance(body, list) else []


def plan_calls(slug: str) -> list[str]:
    ws = f"/workspaces/{slug}"
    p = ws + "/projects/{pid}"
    return [
        f"GET /users/me/",
        f"GET {ws}/features",
        f"GET {ws}/work-item-types/                    (workspace-scoped types; 402 if plan-gated)",
        f"GET {ws}/work-item-relation-definitions/     (where hierarchy rules may live)",
        f"GET {ws}/work-item-types/hierarchy/          (speculative — expect 404)",
        f"GET {ws}/initiatives",
        f"GET {ws}/members-lite  +  {ws}/members",
        f"GET {ws}/projects/                           (cursor-paginated)",
        f"GET {ws}/work-items?per_page=3  +  /work-items/count",
        f"GET {ws}/work-items/search?search=a&per_page=3   (+ external_id filter if one is found)",
        f"--- per project, first {DEEP_PROJECTS} (preferring {PREFER}) ---",
        f"GET {p}/features",
        f"GET {p}/issue-types/                          (old route)",
        f"GET {p}/work-item-types                       (new route)",
        f"GET {p}/issues/?per_page=3                    (old route)",
        f"GET {p}/work-items?per_page=3                 (new route)",
        f"GET {p}/epics",
        f"GET {p}/states/",
        f"GET {p}/modules/  → GET {p}/modules/{{mid}}/module-issues/ (first module)",
        f"GET {p}/work-items/{{id}}?expand=type,parent,module_ids   (one item, full schema)",
        f"GET {ws}/work-items/{{IDENT}}-{{seq}}                     (retrieve by identifier)",
        f"--- remaining projects: features + work-item-types only ---",
    ]


def main() -> None:
    plane._load_dotenv()
    slug = os.environ.get("PLANE_WORKSPACE_SLUG", "<slug>")
    if "--plan" in sys.argv:
        print("\n".join(plan_calls(slug)))
        return
    plane._resolve_secrets()
    slug = plane._require("PLANE_WORKSPACE_SLUG")
    plane._require("PLANE_API_KEY")
    ws = f"/workspaces/{slug}"
    findings: dict = {"slug": slug, "projects": {}}

    _, me = get("users/me", "/users/me/")
    findings["me_keys"] = summarize(me)
    _, wsf = get("ws features", f"{ws}/features")
    findings["workspace_features"] = wsf if isinstance(wsf, dict) else None
    st, wstypes = get("ws work-item-types", f"{ws}/work-item-types/")
    findings["ws_work_item_types"] = {"status": st, "rows": [
        {k: t.get(k) for k in ("id", "name", "level", "is_epic", "is_default", "is_active", "project_ids", "external_id", "external_source")}
        for t in rows(wstypes)]}
    if st != 200:
        findings["ws_work_item_types"]["body"] = wstypes
    st, reldefs = get("ws relation-definitions", f"{ws}/work-item-relation-definitions/")
    findings["relation_definitions"] = {"status": st, "rows": rows(reldefs)[:10] if st == 200 else reldefs}
    st, hier = get("ws types/hierarchy (spec)", f"{ws}/work-item-types/hierarchy/")
    findings["hierarchy_speculative"] = {"status": st, "body": hier}
    st, inits = get("ws initiatives", f"{ws}/initiatives")
    findings["initiatives"] = {"status": st, "count": len(rows(inits)),
                               "item_keys": summarize(inits), "body_if_error": None if st == 200 else inits}
    st, mem = get("ws members-lite", f"{ws}/members-lite")
    findings["members_lite"] = {"status": st, "shape": summarize(mem), "body_if_error": None if st == 200 else mem}
    st, mem2 = get("ws members", f"{ws}/members")
    findings["members"] = {"status": st, "shape": summarize(mem2), "body_if_error": None if st == 200 else mem2}

    # projects
    projects: list[dict] = []
    params: dict = {"per_page": 100}
    while True:
        st, page = get("projects", f"{ws}/projects/", params)
        projects.extend(rows(page))
        if not (isinstance(page, dict) and page.get("next_page_results") and page.get("next_cursor")):
            break
        params = {"per_page": 100, "cursor": page["next_cursor"]}
    findings["project_record_keys"] = sorted(projects[0]) if projects else None
    findings["projects_list"] = [
        {k: p.get(k) for k in ("id", "name", "identifier", "cycle_view", "module_view", "is_epic_enabled",
                               "is_issue_type_enabled", "is_time_tracking_enabled", "is_workflow_enabled",
                               "archived_at", "network")}
        for p in projects]

    st, wsitems = get("ws work-items", f"{ws}/work-items", {"per_page": 3})
    findings["ws_work_items"] = {"status": st, "shape": summarize(wsitems), "body_if_error": None if st == 200 else wsitems}
    st, cnt = get("ws work-items/count", f"{ws}/work-items/count")
    findings["ws_work_items_count"] = {"status": st, "body": cnt}
    st, srch = get("ws work-items/search", f"{ws}/work-items/search", {"search": "a", "per_page": 3})
    findings["ws_search"] = {"status": st, "shape": summarize(srch), "body_if_error": None if st == 200 else srch}

    # choose deep projects
    active = [p for p in projects if not p.get("archived_at")]
    def rank(p: dict) -> tuple:
        name = (p.get("name") or "").lower(); ident = p.get("identifier") or ""
        return (0 if any(k.lower() in name or k == ident for k in PREFER) else 1, name)
    active.sort(key=rank)
    deep, rest = active[:DEEP_PROJECTS], active[DEEP_PROJECTS:]
    external_probe_done = False

    for p in deep:
        pid, ident, pname = p["id"], p.get("identifier"), p.get("name")
        pp = f"{ws}/projects/{pid}"
        rec: dict = {"name": pname, "identifier": ident}
        _, feats = get(f"[{ident}] features", f"{pp}/features")
        rec["features"] = feats
        st, old_types = get(f"[{ident}] issue-types/ (old)", f"{pp}/issue-types/")
        rec["issue_types_old"] = {"status": st, "rows": [
            {k: t.get(k) for k in ("id", "name", "level", "is_epic", "is_default", "is_active")} for t in rows(old_types)]
            if st == 200 else old_types}
        st, new_types = get(f"[{ident}] work-item-types (new)", f"{pp}/work-item-types")
        rec["work_item_types_new"] = {"status": st, "rows": [
            {k: t.get(k) for k in ("id", "name", "level", "is_epic", "is_default", "is_active", "project_ids")} for t in rows(new_types)]
            if st == 200 else new_types}
        if st == 200 and rows(new_types):
            rec["work_item_type_record_keys"] = sorted(rows(new_types)[0])
        st, old_items = get(f"[{ident}] issues/ (old)", f"{pp}/issues/", {"per_page": 3})
        rec["issues_old"] = {"status": st, "shape": summarize(old_items), "body_if_error": None if st == 200 else old_items}
        st, new_items = get(f"[{ident}] work-items (new)", f"{pp}/work-items", {"per_page": 3})
        rec["work_items_new"] = {"status": st, "shape": summarize(new_items), "body_if_error": None if st == 200 else new_items}
        st, epics = get(f"[{ident}] epics", f"{pp}/epics")
        rec["epics"] = {"status": st, "shape": summarize(epics), "body_if_error": None if st == 200 else epics}
        st, states = get(f"[{ident}] states", f"{pp}/states/")
        rec["states"] = [{k: s.get(k) for k in ("name", "group")} for s in rows(states)]
        st, mods = get(f"[{ident}] modules", f"{pp}/modules/")
        mod_rows = rows(mods)
        rec["modules"] = {"status": st, "count": len(mod_rows)}
        # D3 evidence: an item that is BOTH parented (under an epic) AND a module member
        d3 = None
        for m in mod_rows[:3]:
            st, members = get(f"[{ident}] module-issues", f"{pp}/modules/{m['id']}/module-issues/")
            for it in rows(members):
                if it.get("parent"):
                    d3 = {"module": m.get("name"), "item_seq": it.get("sequence_id"), "parent": it.get("parent"),
                          "type_id": it.get("type_id"), "item_keys": sorted(it)}
                    break
            if d3:
                break
        rec["d3_parented_item_in_module"] = d3
        # one full item read
        sample = rows(new_items) or rows(old_items)
        if sample:
            iid = sample[0]["id"]
            st, one = get(f"[{ident}] work-items/{{id}} expand", f"{pp}/work-items/{iid}",
                          {"expand": "type,parent,module_ids,cycle,state"})
            if isinstance(one, dict):
                rec["one_item"] = {"status": st, "keys": sorted(one),
                                   "external_id": one.get("external_id"), "external_source": one.get("external_source"),
                                   "type": one.get("type"), "type_id": one.get("type_id"),
                                   "module_ids": one.get("module_ids"), "cycle": one.get("cycle"),
                                   "parent": one.get("parent"), "sequence_id": one.get("sequence_id")}
                seq = one.get("sequence_id")
                if ident and seq:
                    st, byid = get(f"[{ident}] work-items/{ident}-{seq}", f"{ws}/work-items/{ident}-{seq}")
                    rec["retrieve_by_identifier"] = {"status": st, "ok": isinstance(byid, dict) and byid.get("id") == iid,
                                                     "body_if_error": None if st == 200 else byid}
            else:
                rec["one_item"] = {"status": st, "body": one}
        # external_id queryability: find any item with external_id in the pages we have
        if not external_probe_done:
            for it in rows(new_items) + rows(old_items):
                if it.get("external_id"):
                    st, byext = get(f"[{ident}] search by external_id", f"{ws}/work-items/search",
                                    {"search": "", "external_id": it["external_id"],
                                     "external_source": it.get("external_source") or ""})
                    rec["search_by_external_id"] = {"status": st, "shape": summarize(byext),
                                                    "matched": any(r.get("id") == it["id"] for r in rows(byext))}
                    external_probe_done = True
                    break
        findings["projects"][ident or pid] = rec

    for p in rest:
        pid, ident = p["id"], p.get("identifier")
        pp = f"{ws}/projects/{pid}"
        rec = {"name": p.get("name"), "identifier": ident}
        _, feats = get(f"[{ident}] features", f"{pp}/features")
        rec["features"] = feats
        st, new_types = get(f"[{ident}] work-item-types", f"{pp}/work-item-types")
        rec["work_item_types_new"] = {"status": st, "rows": [
            {k: t.get(k) for k in ("id", "name", "level", "is_epic", "is_default", "is_active")} for t in rows(new_types)]
            if st == 200 else new_types}
        findings["projects"][ident or pid] = rec

    findings["external_id_probe_done"] = external_probe_done
    findings["call_log"] = log
    (HERE / "probe-report.json").write_text(json.dumps(findings, indent=2, default=str))
    print(f"\n{len(log)} calls; report → {HERE / 'probe-report.json'}")


if __name__ == "__main__":
    main()
