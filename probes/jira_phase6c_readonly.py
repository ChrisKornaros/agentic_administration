"""Phase 6c — read-only probe of Jira Cloud's dates and custom fields.

The live check before the Jira adapter writes dates and a custom-field
pass-through (roadmap/14 §9 row 6c, D41): is the system `duedate` field
there, which custom field is the site's Start date (and of what custom
type), which date and custom fields each issue type's create screen and an
existing issue's edit screen accept, what the option fields allow, the
shape of a set value, and where the Start date field applies (its
contexts). Findings go to the design repo (agentic_optimization_research
roadmap/14); this file is the evidence of *how* they were read.

Every call is a GET — nothing is written. The token and the account email
come from the secrets boundary (`server/secrets.py`): `JIRA_API_TOKEN` and
`JIRA_USER`, each an env var or a Bitwarden item via `<NAME>_BW_ITEM` (the
email as that item's login username: `JIRA_USER_BW_FIELD=username`).
Neither is printed. Throttled ~1 s/call. Stdlib only.

Usage:
  uv run python probes/jira_phase6c_readonly.py --plan    # call list, no network
  JIRA_SITE=https://<site>.atlassian.net JIRA_PROJECT=<KEY> \\
  JIRA_API_TOKEN_BW_ITEM=<item> JIRA_USER_BW_ITEM=<item> JIRA_USER_BW_FIELD=username \\
  BW_SESSION=... uv run python probes/jira_phase6c_readonly.py
  # writes jira-6c-probe-report.json next to this file (board content — gitignored)
"""
from __future__ import annotations

import argparse
import base64
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
sys.path.insert(0, str(HERE.parent))
from server import secrets  # noqa: E402  (the one secret boundary)

THROTTLE = 1.0
USER_AGENT = "agentic-administration/0.0 (jira probe; +https://github.com/ChrisKornaros/agentic_administration)"
KEEP_HEADERS = re.compile(r"ratelimit|retry-after", re.I)
# the Start date field goes by its name; Advanced Roadmaps' own fields (Target start / end) are listed apart
START_NAME = re.compile(r"^start date$", re.I)
START_CUSTOM = re.compile(r"baseline-start|jpo-custom-field", re.I)
OPTION_SAMPLE = 5  # allowed values kept per option field

log: list[dict] = []


class Probe:
    def __init__(self, site: str, user: str, token: str) -> None:
        self.site = site.rstrip("/")
        self._auth = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()

    def get(self, label: str, path: str, params: dict | None = None) -> tuple[int, object]:
        """GET site+path; record (status, response shape, rate headers) and return it."""
        url = f"{self.site}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, method="GET", headers={
            "Authorization": self._auth, "Accept": "application/json", "User-Agent": USER_AGENT,
        })
        status, raw, hdrs = 0, "", {}
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, raw, hdrs = resp.status, resp.read().decode("utf-8"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read().decode("utf-8", "replace")
            hdrs = dict(exc.headers or {})
        except urllib.error.URLError as exc:
            status, raw = -1, str(exc.reason)
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw[:400]
        kept = {k: v for k, v in hdrs.items() if KEEP_HEADERS.search(k)}
        log.append({"label": label, "path": path, "params": params, "status": status,
                    "shape": summarize(body), "headers": kept})
        print(f"{status:>4}  {label:<36} {path}{'?' + urllib.parse.urlencode(params) if params else ''}", flush=True)
        time.sleep(THROTTLE)
        return status, body


def summarize(body: object) -> object:
    """Shape of a response: keys and counts, never full content."""
    if isinstance(body, dict):
        for env in ("values", "issues", "fields"):
            if isinstance(body.get(env), list):
                first = body[env][0] if body[env] else None
                return {"envelope": sorted(k for k in body if k != env), "list": env, "count": len(body[env]),
                        "item_keys": sorted(first) if isinstance(first, dict) else None}
        return {"keys": sorted(body)}
    if isinstance(body, list):
        first = body[0] if body else None
        return {"list_len": len(body), "item_keys": sorted(first) if isinstance(first, dict) else None}
    return body


def rows(body: object, *envelopes: str) -> list:
    if isinstance(body, dict):
        for env in envelopes or ("values", "issues", "fields"):
            if isinstance(body.get(env), list):
                return body[env]
    return body if isinstance(body, list) else []


def error(status: int, body: object) -> object:
    return None if status == 200 else body


def pick(d: object, *keys: str) -> dict:
    return {k: d.get(k) for k in keys} if isinstance(d, dict) else {}


def field_row(x: dict) -> dict:
    """One field as a screen (createmeta / editmeta) describes it."""
    schema = x.get("schema") or {}
    allowed = x.get("allowedValues")
    row = {"id": x.get("fieldId") or x.get("key"), "name": x.get("name"), "required": x.get("required"),
           "type": schema.get("type"), "items": schema.get("items"), "custom": schema.get("custom"),
           "operations": x.get("operations")}
    if isinstance(allowed, list):
        row["allowed_count"] = len(allowed)
        row["allowed_sample"] = [pick(a, "id", "value", "name") for a in allowed[:OPTION_SAMPLE]]
    return row


def is_date_or_custom(fid: str | None) -> bool:
    return bool(fid) and (fid == "duedate" or fid.startswith("customfield_"))


def plan_calls(project: str) -> list[str]:
    return [
        "GET /rest/api/3/myself                                   (auth works; timeZone)",
        f"GET /rest/api/3/project/{project}?expand=issueTypes       (the types to read screens for)",
        "GET /rest/api/3/field                                    (duedate; the Start date field; every custom field's type)",
        "GET /rest/api/3/field/{start}/context                    (where the Start date field applies; admin)",
        f"--- per issue type of {project} ---",
        f"GET /rest/api/3/issue/createmeta/{project}/issuetypes/{{id}}   (create-screen fields + allowed values)",
        f"GET /rest/api/3/search/jql?jql=project={project} AND issuetype={{id}}  (one issue of the type, newest)",
        "GET /rest/api/3/issue/{key}/editmeta                     (edit-screen fields of that issue)",
        "GET /rest/api/3/issue/{key}?fields=duedate,{start},…     (the shape of a set date / custom value)",
    ]


def probe(pr: Probe, key: str) -> dict:
    f: dict = {"site": pr.site, "project_key": key}

    st, me = pr.get("myself", "/rest/api/3/myself")
    f["myself"] = {"status": st, **pick(me, "accountType", "timeZone")}
    if st != 200:
        f["myself"]["body"] = me
        return f  # auth failed: nothing else will answer

    st, proj = pr.get("project", f"/rest/api/3/project/{key}", {"expand": "issueTypes"})
    if st != 200:
        f["project"] = {"status": st, "body": proj}
        return f
    types = [pick(t, "id", "name", "hierarchyLevel", "subtask") for t in proj.get("issueTypes") or []]
    f["project"] = {**pick(proj, "id", "key", "style"), "issue_types": types}

    # -- the fields: duedate, Start date, and every custom field's type -------------------
    st, fields = pr.get("field (all)", "/rest/api/3/field")
    all_fields = fields if isinstance(fields, list) else []
    due = next((x for x in all_fields if x.get("id") == "duedate"), None)
    starts = [x for x in all_fields if x.get("custom") and START_NAME.match(x.get("name") or "")]
    roadmap = [x for x in all_fields if x.get("custom") and x not in starts
               and START_CUSTOM.search((x.get("schema") or {}).get("custom") or "")]
    f["duedate"] = {**pick(due or {}, "id", "name", "orderable", "navigable", "searchable", "clauseNames"),
                    "schema": (due or {}).get("schema"), "present": due is not None}
    f["start_date_fields"] = [{**pick(x, "id", "name", "clauseNames"), "schema": x.get("schema")} for x in starts]
    f["roadmap_fields"] = [{**pick(x, "id", "name"), "schema": x.get("schema")} for x in roadmap]  # not the start date
    f["custom_fields"] = [
        {**pick(x, "id", "name"), "type": (x.get("schema") or {}).get("type"),
         "items": (x.get("schema") or {}).get("items"), "custom": (x.get("schema") or {}).get("custom")}
        for x in all_fields if x.get("custom")]
    start_ids = [x.get("id") for x in starts]
    for sid in start_ids[:2]:
        st, ctx = pr.get(f"field {sid} context", f"/rest/api/3/field/{sid}/context")
        f.setdefault("start_date_contexts", {})[sid] = {
            "status": st, "error": error(st, ctx),
            "rows": [pick(c, "id", "name", "isGlobalContext", "isAnyIssueType") for c in rows(ctx, "values")]}

    # -- per issue type: what the create screen takes, an issue's edit screen and values ----
    f["types"] = {}
    for t in types:
        tid, tname = t.get("id"), t.get("name")
        entry: dict = {"id": tid, "hierarchyLevel": t.get("hierarchyLevel")}
        st, cm = pr.get(f"createmeta {tname}", f"/rest/api/3/issue/createmeta/{key}/issuetypes/{tid}")
        create = [field_row(x) for x in rows(cm, "fields", "values")]
        entry["create"] = {"status": st, "error": error(st, cm),
                           "date_and_custom": [r for r in create if is_date_or_custom(r["id"])],
                           "all_ids": sorted(r["id"] or "" for r in create)}
        entry["create"]["has_duedate"] = "duedate" in entry["create"]["all_ids"]
        entry["create"]["has_start"] = [s for s in start_ids if s in entry["create"]["all_ids"]]

        jql = f"project = {key} AND issuetype = {tid} ORDER BY created DESC"
        st, found = pr.get(f"one {tname}", "/rest/api/3/search/jql", {"jql": jql, "maxResults": 1, "fields": "summary"})
        issues = rows(found, "issues")
        if not issues:
            entry["issue"] = {"status": st, "error": error(st, found), "key": None}
            f["types"][tname] = entry
            continue
        ikey = issues[0].get("key")
        st, em = pr.get(f"editmeta {ikey}", f"/rest/api/3/issue/{ikey}/editmeta")
        edit_fields = (em.get("fields") if isinstance(em, dict) else None) or {}
        edit = [field_row({**v, "key": k}) for k, v in edit_fields.items()]
        wanted = ["duedate", *start_ids, *(r["id"] for r in edit if is_date_or_custom(r["id"]))]
        wanted = list(dict.fromkeys(w for w in wanted if w))
        st2, one = pr.get(f"issue {ikey} values", f"/rest/api/3/issue/{ikey}", {"fields": ",".join(wanted)})
        values = (one.get("fields") if isinstance(one, dict) else None) or {}
        entry["issue"] = {
            "key": ikey,
            "edit": {"status": st, "error": error(st, em),
                     "date_and_custom": [r for r in edit if is_date_or_custom(r["id"])],
                     "has_duedate": "duedate" in edit_fields,
                     "has_start": [s for s in start_ids if s in edit_fields]},
            "values": {"status": st2, "set": {k: v for k, v in values.items() if v not in (None, [], "")},
                       "unset": sorted(k for k, v in values.items() if v in (None, [], ""))},
        }
        f["types"][tname] = entry
    return f


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jira_phase6c_readonly.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--site", default=os.environ.get("JIRA_SITE"), help="https://<site>.atlassian.net (or JIRA_SITE)")
    parser.add_argument("--project", default=os.environ.get("JIRA_PROJECT"), help="project key (or JIRA_PROJECT)")
    parser.add_argument("--plan", action="store_true", help="print the call list; no network")
    args = parser.parse_args(argv)
    if args.plan:
        print("\n".join(plan_calls(args.project or "<KEY>")))
        return 0
    if not (args.site and args.project):
        parser.error("--site and --project (or JIRA_SITE / JIRA_PROJECT) are required")
    try:
        pr = Probe(args.site, secrets.get("JIRA_USER"), secrets.get("JIRA_API_TOKEN"))
    except secrets.SecretUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = probe(pr, args.project)
    findings["call_log"] = log
    out = HERE / "jira-6c-probe-report.json"
    out.write_text(json.dumps(findings, indent=2, default=str))
    print(f"\n{len(log)} calls, all GET; report → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
