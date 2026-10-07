"""Phase 6c — read-only probe of Plane's dates and work-item properties.

The live check before the Plane adapter writes dates and a custom-field
pass-through (roadmap/14 §9 row 6c, D41): which work-item properties each
type carries and of what kind (`property_type`, `is_multi`, settings), an
option property's options (on its record, and by the `options/` route),
how a set value reads back, whether one read
returns all of an item's values, and which item reads carry `start_date`
and `target_date` (the project list, by id, by key; `cycle_id` is recorded
alongside, for the Phase 6 gate's finding 6). The 2026-10-05 Food Content
run proved the value write (`POST …/values/`, an upsert); this proves the
reads the adapter will check and read back with. Findings go to the design
repo (agentic_optimization_research roadmap/14); this file is the evidence
of *how* they were read.

Every call is a GET — nothing is written. The token comes from the secrets
boundary (`server/secrets.py`): `PLANE_API_KEY`, an env var or a Bitwarden
item via `PLANE_API_KEY_BW_ITEM` (+ `_BW_FIELD`). It is never printed. The
User-Agent is the adapter's, since Cloudflare bans urllib's default.
Throttled ~1.5 s/call. Stdlib only.

Usage:
  uv run python probes/plane_phase6c_readonly.py --plan    # call list, no network
  PLANE_API_KEY_BW_ITEM=<item> PLANE_API_KEY_BW_FIELD=API BW_SESSION=... \\
  uv run python probes/plane_phase6c_readonly.py --workspace <slug> --project <ID> [--project <ID> …] \\
      [--item <KEY> …]
  # writes plane-6c-probe-report.json next to this file (board content — gitignored)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from adapters.plane.transport import DEFAULT_BASE_URL, USER_AGENT  # noqa: E402  (Cloudflare's UA rule)
from server import secrets  # noqa: E402  (the one secret boundary)

THROTTLE = 1.5
DATE_KEYS = ("start_date", "target_date", "cycle_id")
PROPERTY_KEYS = ("id", "name", "display_name", "property_type", "relation_type", "is_multi", "is_required",
                 "is_active", "default_value", "settings", "sort_order", "external_id")

log: list[dict] = []


class Probe:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self._token = token
        self.base_url = base_url.rstrip("/")

    def get(self, label: str, path: str, params: dict | None = None) -> tuple[int, object]:
        """GET base+path; record (status, response shape) and return it."""
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, method="GET", headers={
            "X-API-Key": self._token, "Accept": "application/json", "User-Agent": USER_AGENT,
        })
        status, raw = 0, ""
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, raw = resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:
            status, raw = -1, str(exc.reason)
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw[:400]  # a Cloudflare HTML page, say
        log.append({"label": label, "path": path, "params": params, "status": status, "shape": summarize(body)})
        print(f"{status:>4}  {label:<40} {path}{'?' + urllib.parse.urlencode(params) if params else ''}", flush=True)
        time.sleep(THROTTLE)
        return status, body


def summarize(body: object) -> object:
    """Shape of a response: keys of a dict / first element; never full content."""
    if isinstance(body, dict):
        if isinstance(body.get("results"), list):
            first = body["results"][0] if body["results"] else None
            return {"envelope": sorted(k for k in body if k != "results"), "count": len(body["results"]),
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


def error(status: int, body: object) -> object:
    return None if status == 200 else body


def pick(d: object, *keys: str) -> dict:
    return {k: d.get(k) for k in keys} if isinstance(d, dict) else {}


def dates(rec: object) -> dict:
    """Which of the date keys a record carries, and their values."""
    if not isinstance(rec, dict):
        return {"record": False}
    return {k: rec.get(k) for k in DATE_KEYS if k in rec} | {"missing": [k for k in DATE_KEYS if k not in rec]}


def plan_calls(slug: str) -> list[str]:
    ws = f"/workspaces/{slug}"
    p = ws + "/projects/{pid}"
    return [
        f"GET {ws}/projects/                                       (resolve each --project)",
        "--- per project ---",
        f"GET {p}/work-item-types/",
        f"GET {p}/work-item-types/{{type}}/work-item-properties/    (per type: kind, is_multi, settings)",
        f"GET {p}/work-item-types/{{type}}/work-item-properties/{{prop}}/options/   (per option property)",
        f"GET {p}/work-items/?per_page=100                         (first page: which rows carry the dates)",
        "--- per sample item (newest of each type with properties, or each --item) ---",
        f"GET {p}/work-items/{{id}}/                               (by id: dates, cycle_id)",
        f"GET {ws}/work-items/{{KEY}}/                             (by key: dates, cycle_id)",
        f"GET {p}/work-items/{{id}}/work-item-properties/{{prop}}/values/   (per property: a value's shape)",
        f"GET {p}/work-items/{{id}}/work-item-properties/          (speculative: every value in one read?)",
    ]


def probe_project(pr: Probe, slug: str, proj: dict, items: list[str]) -> dict:
    ws = f"/workspaces/{slug}"
    pp = f"{ws}/projects/{proj['id']}"
    ident = proj.get("identifier")
    f: dict = {**pick(proj, "id", "identifier", "name", "timezone")}

    st, types_body = pr.get(f"{ident} work-item-types", f"{pp}/work-item-types/")
    types = [pick(t, "id", "name", "is_epic", "is_default", "is_active") for t in rows(types_body)]
    f["types"] = {"status": st, "error": error(st, types_body), "rows": types}

    props_by_type: dict[str, list[dict]] = {}
    f["properties"] = {}
    for t in types:
        st, pbody = pr.get(f"{ident} {t['name']} properties", f"{pp}/work-item-types/{t['id']}/work-item-properties/")
        props = []
        for x in rows(pbody):  # an option property's options ride on its record
            props.append(pick(x, *PROPERTY_KEYS) | {"embedded_options": [
                pick(o, "id", "name", "is_default", "is_active", "sort_order") for o in x.get("options") or []]})
        entry: dict = {"status": st, "error": error(st, pbody), "rows": props,
                       "record_keys": sorted(rows(pbody)[0]) if rows(pbody) and isinstance(rows(pbody)[0], dict) else None}
        for prop in props:
            if (prop.get("property_type") or "").upper() == "OPTION":
                st2, obody = pr.get(f"{ident} {prop.get('display_name') or prop.get('name')} options",
                                    f"{pp}/work-item-types/{t['id']}/work-item-properties/{prop['id']}/options/")
                prop["options"] = {"status": st2, "error": error(st2, obody),
                                   "rows": [pick(o, "id", "name", "is_default", "sort_order") for o in rows(obody)]}
        f["properties"][t["name"]] = entry
        if props:
            props_by_type[t["id"]] = props

    st, list_body = pr.get(f"{ident} work-items (first page)", f"{pp}/work-items/", {"per_page": 100})
    listed = [r for r in rows(list_body) if isinstance(r, dict)]
    f["list"] = {"status": st, "count": len(listed),
                 "carries": {k: sum(1 for r in listed if k in r) for k in DATE_KEYS},
                 "set": {k: sum(1 for r in listed if r.get(k)) for k in DATE_KEYS},
                 "item_keys": sorted(listed[0]) if listed else None}

    # the sample: each --item key, else the newest listed item of each type that carries properties
    samples: list[tuple[str, dict | None]] = [(k, None) for k in items]
    if not samples:
        for type_id in props_by_type:
            row = next((r for r in listed if (r.get("type_id") or r.get("type")) == type_id), None)
            if row is not None:
                samples.append((f"{ident}-{row.get('sequence_id')}", row))
    f["samples"] = []
    for key, row in samples:
        st, by_key = pr.get(f"{key} by key", f"{ws}/work-items/{key}/")
        if st != 200 or not isinstance(by_key, dict):
            f["samples"].append({"key": key, "by_key": {"status": st, "error": by_key}})
            continue
        iid = by_key["id"]
        st2, by_id = pr.get(f"{key} by id", f"{pp}/work-items/{iid}/")
        sample: dict = {"key": key, "type_id": by_key.get("type_id"),
                        "list": dates(row) if row is not None else None,
                        "by_key": dates(by_key), "by_id": {"status": st2, **dates(by_id)}, "values": {}}
        for prop in props_by_type.get(by_key.get("type_id") or "", []):
            st3, vbody = pr.get(f"{key} {prop.get('display_name') or prop.get('name')} values",
                                f"{pp}/work-items/{iid}/work-item-properties/{prop['id']}/values/")
            sample["values"][prop.get("display_name") or prop["id"]] = {
                "status": st3, "shape": summarize(vbody), "body": vbody,
                "property_type": prop.get("property_type"), "is_multi": prop.get("is_multi")}
        st4, all_values = pr.get(f"{key} every value (speculative)", f"{pp}/work-items/{iid}/work-item-properties/")
        sample["all_values"] = {"status": st4, "shape": summarize(all_values), "error": error(st4, all_values)}
        f["samples"].append(sample)
    return f


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plane_phase6c_readonly.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", default=os.environ.get("PLANE_WORKSPACE_SLUG"), help="workspace slug")
    parser.add_argument("--project", action="append", default=[], help="project identifier, name or id (repeatable)")
    parser.add_argument("--item", action="append", default=[], help="sample item key, e.g. AA-12 (repeatable)")
    parser.add_argument("--plan", action="store_true", help="print the call list; no network")
    args = parser.parse_args(argv)
    if args.plan:
        print("\n".join(plan_calls(args.workspace or "<slug>")))
        return 0
    if not (args.workspace and args.project):
        parser.error("--workspace and at least one --project are required")
    try:
        pr = Probe(secrets.get("PLANE_API_KEY"))
    except secrets.SecretUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    st, projects = pr.get("projects", f"/workspaces/{args.workspace}/projects/")
    if st != 200:
        print(f"error: the project list answered {st}: {projects}", file=sys.stderr)
        return 2
    findings: dict = {"workspace": args.workspace, "projects": {}}
    for ref in args.project:
        proj = next((p for p in rows(projects) if ref in (p.get("id"), p.get("identifier"))
                     or ref.lower() == (p.get("name") or "").lower()), None)
        if proj is None:
            findings["projects"][ref] = {"error": "not in the workspace"}
            continue
        mine = [k for k in args.item if k.upper().startswith(f"{proj.get('identifier')}-")]
        findings["projects"][proj.get("identifier") or ref] = probe_project(pr, args.workspace, proj, mine)
    findings["call_log"] = log
    out = HERE / "plane-6c-probe-report.json"
    out.write_text(json.dumps(findings, indent=2, default=str))
    print(f"\n{len(log)} calls, all GET; report → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
