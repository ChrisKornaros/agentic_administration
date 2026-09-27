"""Phase 5 — read-only probe of Jira Cloud (REST v3 + Agile 1.0).

The live check that gates the Jira adapter (roadmap/14 §9 Phase 5, D2):
what the project is (company- vs team-managed), which issue types it has
and at which hierarchy level, the statuses and transitions per type, which
fields the create screens carry, what the board and its sprints look like,
which search endpoint answers, whether any read surface can back an exact
idempotency lookup (JQL functions, field operators, entity properties),
and which rate-limit headers come back. Findings go to the design repo
(agentic_optimization_research roadmap/14); this file is the evidence of
*how* they were read.

Every call is a GET — nothing is written. The token and the account email
come from the secrets boundary (`server/secrets.py`): `JIRA_API_TOKEN` and
`JIRA_USER`, each an env var or a Bitwarden item via `<NAME>_BW_ITEM` (the
email as that item's login username: `JIRA_USER_BW_FIELD=username`).
Neither is printed. Throttled ~1 s/call. Stdlib only.

Usage:
  uv run python probes/jira_phase5_readonly.py --plan    # call list, no network
  JIRA_SITE=https://<site>.atlassian.net JIRA_PROJECT=<KEY> \\
  JIRA_API_TOKEN_BW_ITEM=<item> JIRA_USER_BW_ITEM=<item> JIRA_USER_BW_FIELD=username \\
  BW_SESSION=... uv run python probes/jira_phase5_readonly.py
  # writes jira-probe-report.json next to this file (board content — gitignored)
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
# response headers worth keeping: the rate-limit surface and the old captcha signal
KEEP_HEADERS = re.compile(r"ratelimit|retry-after|x-seraph|x-arequestid", re.I)
# the JQL functions that could back an exact idempotency lookup
JQL_FUNCTIONS = ("issuesWithRemoteLinksByGlobalId", "issueHistory", "linkedIssues")

log: list[dict] = []
headers_seen: set[str] = set()


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
            body = raw[:400]  # an HTML error page, say
        kept = {k: v for k, v in hdrs.items() if KEEP_HEADERS.search(k)}
        headers_seen.update(k.lower() for k in kept)
        log.append({"label": label, "path": path, "params": params, "status": status,
                    "shape": summarize(body), "headers": kept})
        print(f"{status:>4}  {label:<36} {path}{'?' + urllib.parse.urlencode(params) if params else ''}", flush=True)
        time.sleep(THROTTLE)
        return status, body


def summarize(body: object) -> object:
    """Shape of a response: keys and counts, never full content."""
    if isinstance(body, dict):
        for env in ("values", "issues"):
            if isinstance(body.get(env), list):
                first = body[env][0] if body[env] else None
                return {"envelope": sorted(k for k in body if k != env), "list": env, "count": len(body[env]),
                        "item_keys": sorted(first) if isinstance(first, dict) else None}
        return {"keys": sorted(body)}
    if isinstance(body, list):
        first = body[0] if body else None
        return {"list_len": len(body), "item_keys": sorted(first) if isinstance(first, dict) else None}
    return body


def rows(body: object) -> list:
    if isinstance(body, dict):
        for env in ("values", "issues"):
            if isinstance(body.get(env), list):
                return body[env]
    return body if isinstance(body, list) else []


def error(status: int, body: object) -> object:
    return None if status == 200 else body


def pick(d: object, *keys: str) -> dict:
    return {k: d.get(k) for k in keys} if isinstance(d, dict) else {}


def plan_calls(project: str) -> list[str]:
    p = f"/rest/api/3/project/{project}"
    return [
        "GET /rest/api/3/myself                                  (auth works; timeZone, accountType)",
        "GET /rest/api/3/serverInfo",
        f"GET {p}?expand=issueTypes                    (style: classic = company-managed)",
        "GET /rest/api/3/project/{pid}/hierarchy                 (hierarchy levels; may be gone)",
        f"GET {p}/features",
        "GET /rest/api/3/issuetype                               (hierarchyLevel, subtask, scope)",
        f"GET {p}/statuses                              (statuses per issue type)",
        "GET /rest/api/3/statuscategory  +  /rest/api/3/resolution",
        "GET /rest/api/3/workflowscheme/project?projectId={pid}",
        f"GET /rest/api/3/workflow/search?queryString={project}&expand=transitions,statuses",
        f"GET /rest/api/3/issue/createmeta/{project}/issuetypes  → …/issuetypes/{{id}} per type (create-screen fields)",
        "GET /rest/api/3/field                                   (custom fields: sprint, rank, team, parent)",
        "GET /rest/api/3/label   +   " + f"{p}/components",
        f"GET /rest/api/3/user/assignable/search?project={project}   (counts; is email visible)",
        f"GET /rest/api/3/search/jql?jql=project={project}…          (enhanced search: envelope, paging)",
        f"GET /rest/api/3/search?jql=project={project}               (the old route: still there?)",
        "GET /rest/api/3/jql/autocompletedata                    (JQL functions + field operators for idempotency)",
        "--- when the project has an issue: ---",
        "GET /rest/api/3/issue/{key}?expand=names  +  /transitions  +  /properties  +  /remotelink",
        "--- Agile 1.0 ---",
        f"GET /rest/agile/1.0/board?projectKeyOrId={project}",
        "GET /rest/agile/1.0/board/{id}/configuration  +  /features  +  /sprint  +  /backlog?maxResults=1",
    ]


def probe(pr: Probe, key: str) -> dict:
    f: dict = {"site": pr.site, "project_key": key}

    st, me = pr.get("myself", "/rest/api/3/myself")
    f["myself"] = {"status": st, **pick(me, "accountType", "timeZone", "locale", "active"),
                   "has_account_id": isinstance(me, dict) and bool(me.get("accountId"))}
    if st != 200:
        f["myself"]["body"] = me
        return f  # auth failed: nothing else will answer
    st, info = pr.get("serverInfo", "/rest/api/3/serverInfo")
    f["server_info"] = {"status": st, **pick(info, "deploymentType", "buildNumber", "version")}

    # -- the project -----------------------------------------------------------------
    st, proj = pr.get("project", f"/rest/api/3/project/{key}", {"expand": "issueTypes"})
    if st != 200:
        f["project"] = {"status": st, "body": proj}
        return f
    pid = str(proj.get("id"))
    f["project"] = {**pick(proj, "id", "key", "name", "style", "simplified", "projectTypeKey", "isPrivate"),
                    "record_keys": sorted(proj),
                    "issue_types": [pick(t, "id", "name", "hierarchyLevel", "subtask") for t in proj.get("issueTypes") or []]}
    if proj.get("style") != "classic":
        print(f"\nWARNING: {key} is style {proj.get('style')!r} (team-managed); Phase 5 targets a company-managed "
              "project (style 'classic').\n", flush=True)
    st, hier = pr.get("project hierarchy", f"/rest/api/3/project/{pid}/hierarchy")
    f["project_hierarchy"] = {"status": st, "body": hier if st == 200 else error(st, hier)}
    st, feats = pr.get("project features", f"/rest/api/3/project/{key}/features")
    f["project_features"] = {"status": st, "features": [pick(x, "feature", "state", "toggleLocked") for x in
                                                        (feats.get("features") if isinstance(feats, dict) else []) or []],
                             "error": error(st, feats)}

    # -- types, statuses, workflows ---------------------------------------------------------
    st, types = pr.get("issuetypes (all)", "/rest/api/3/issuetype")
    f["issue_types_all"] = {"status": st, "rows": [
        {**pick(t, "id", "name", "hierarchyLevel", "subtask", "untranslatedName"),
         "scope": (t.get("scope") or {}).get("type"), "scope_project": ((t.get("scope") or {}).get("project") or {}).get("key")}
        for t in (types if isinstance(types, list) else [])]}
    st, sts = pr.get("project statuses", f"/rest/api/3/project/{key}/statuses")
    f["statuses_by_type"] = {"status": st, "rows": [
        {"type": t.get("name"), "statuses": [{**pick(s, "id", "name"), "category": (s.get("statusCategory") or {}).get("key")}
                                             for s in t.get("statuses") or []]}
        for t in (sts if isinstance(sts, list) else [])], "error": error(st, sts)}
    st, cats = pr.get("statuscategory", "/rest/api/3/statuscategory")
    f["status_categories"] = [pick(c, "id", "key", "name") for c in (cats if isinstance(cats, list) else [])]
    st, res = pr.get("resolution", "/rest/api/3/resolution")
    f["resolutions"] = {"status": st, "rows": [pick(r, "id", "name") for r in (res if isinstance(res, list) else [])]}
    st, scheme = pr.get("workflowscheme/project", "/rest/api/3/workflowscheme/project", {"projectId": pid})
    f["workflow_scheme"] = {"status": st, "rows": [
        {"projects": v.get("projectIds"),
         **pick(v.get("workflowScheme") or {}, "id", "name", "defaultWorkflow", "issueTypeMappings")}
        for v in rows(scheme)], "error": error(st, scheme)}
    st, wfs = pr.get("workflow/search", "/rest/api/3/workflow/search",
                     {"queryString": key, "expand": "transitions,statuses", "maxResults": 20})
    f["workflows"] = {"status": st, "error": error(st, wfs), "rows": [
        {"name": (w.get("id") or {}).get("name"),
         "statuses": [s.get("name") or s.get("id") for s in w.get("statuses") or []],
         "transitions": [{**pick(t, "id", "name", "to", "type"), "from": t.get("from")} for t in w.get("transitions") or []]}
        for w in rows(wfs)]}

    # -- what a create may carry ------------------------------------------------------------
    st, cm = pr.get("createmeta issuetypes", f"/rest/api/3/issue/createmeta/{key}/issuetypes")
    create: dict = {"status": st, "error": error(st, cm), "types": {}}
    for t in rows(cm) or (cm.get("issueTypes") if isinstance(cm, dict) else []) or []:
        st2, fields = pr.get(f"createmeta {t.get('name')}", f"/rest/api/3/issue/createmeta/{key}/issuetypes/{t.get('id')}")
        field_rows = rows(fields) or (fields.get("fields") if isinstance(fields, dict) else []) or []
        create["types"][t.get("name")] = {
            "id": t.get("id"), "status": st2, "hierarchyLevel": t.get("hierarchyLevel"), "subtask": t.get("subtask"),
            "fields": [{"id": x.get("fieldId") or x.get("key"), "name": x.get("name"), "required": x.get("required"),
                        "type": (x.get("schema") or {}).get("type"), "custom": (x.get("schema") or {}).get("custom"),
                        "has_default": x.get("hasDefaultValue")} for x in field_rows],
        }
    f["create_meta"] = create
    st, fields = pr.get("field (all)", "/rest/api/3/field")
    f["custom_fields"] = [
        {**pick(x, "id", "name"), "custom": (x.get("schema") or {}).get("custom"), "type": (x.get("schema") or {}).get("type"),
         "clause_names": x.get("clauseNames")}
        for x in (fields if isinstance(fields, list) else []) if x.get("custom")]
    f["system_field_ids"] = sorted(x.get("id") for x in (fields if isinstance(fields, list) else []) if not x.get("custom"))

    # -- labels, components, people -----------------------------------------------------------
    st, labels = pr.get("label", "/rest/api/3/label", {"maxResults": 100})
    f["labels"] = {"status": st, **pick(labels, "total", "isLast"), "values": rows(labels)}
    st, comps = pr.get("components", f"/rest/api/3/project/{key}/components")
    f["components"] = {"status": st, "names": [c.get("name") for c in (comps if isinstance(comps, list) else [])]}
    st, users = pr.get("assignable users", "/rest/api/3/user/assignable/search", {"project": key, "maxResults": 50})
    ulist = users if isinstance(users, list) else []
    f["assignable_users"] = {"status": st, "count": len(ulist),
                             "account_types": sorted({u.get("accountType") for u in ulist}),
                             "email_visible": any(u.get("emailAddress") for u in ulist),
                             "item_keys": sorted(ulist[0]) if ulist else None}

    # -- search -------------------------------------------------------------------------------
    jql = f"project = {key} ORDER BY created DESC"
    st, found = pr.get("search/jql (enhanced)", "/rest/api/3/search/jql",
                       {"jql": jql, "maxResults": 5, "fields": "summary,status,issuetype,parent,labels,components"})
    issues = rows(found)
    f["search_jql"] = {"status": st, "shape": summarize(found), "error": error(st, found),
                       **pick(found, "isLast", "total"), "has_next_token": isinstance(found, dict) and "nextPageToken" in found}
    st, old = pr.get("search (old route)", "/rest/api/3/search", {"jql": jql, "maxResults": 1})
    f["search_old"] = {"status": st, "shape": summarize(old), "error": error(st, old)}
    st, ac = pr.get("jql autocompletedata", "/rest/api/3/jql/autocompletedata")
    if isinstance(ac, dict):
        fnames = {x.get("value") for x in ac.get("visibleFunctionNames") or []}
        fields_ac = {(x.get("displayName") or x.get("value")): x for x in ac.get("visibleFieldNames") or []}
        f["jql"] = {
            "functions_present": {fn: any(fn in (n or "") for n in fnames) for fn in JQL_FUNCTIONS},
            "function_count": len(fnames),
            "operators": {name: fields_ac[name].get("operators") for name in fields_ac
                          if name.lower() in ("labels", "summary", "text", "component", "sprint", "parent", "issue.property", "status")
                          or "[short text]" in name.lower() or "[text field" in name.lower()},
            "property_fields": sorted(n for n in fields_ac if "property" in n.lower())[:20],
        }
    else:
        f["jql"] = {"status": st, "body": ac}

    if issues:
        k = issues[0].get("key")
        st, one = pr.get("issue (one)", f"/rest/api/3/issue/{k}", {"expand": "names"})
        fields_one = (one.get("fields") if isinstance(one, dict) else None) or {}
        names = (one.get("names") if isinstance(one, dict) else None) or {}
        f["one_issue"] = {"status": st, "key": k, "field_keys": sorted(fields_one),
                          "set_custom_fields": {fid: names.get(fid) for fid, v in fields_one.items()
                                                if fid.startswith("customfield_") and v not in (None, [], "")},
                          "description_type": type(fields_one.get("description")).__name__,
                          "parent": pick(fields_one.get("parent") or {}, "id", "key")}
        st, tr = pr.get("issue transitions", f"/rest/api/3/issue/{k}/transitions")
        f["one_issue"]["transitions"] = [
            {**pick(t, "id", "name", "hasScreen", "isGlobal", "isInitial", "isConditional"),
             "to": (t.get("to") or {}).get("name"), "to_category": ((t.get("to") or {}).get("statusCategory") or {}).get("key")}
            for t in (tr.get("transitions") if isinstance(tr, dict) else []) or []]
        st, props = pr.get("issue properties", f"/rest/api/3/issue/{k}/properties")
        f["one_issue"]["properties"] = {"status": st, "body": props}
        st, links = pr.get("issue remotelink", f"/rest/api/3/issue/{k}/remotelink")
        f["one_issue"]["remote_links"] = {"status": st, "count": len(links) if isinstance(links, list) else None}
    else:
        f["one_issue"] = None  # a fresh project: transitions come from the workflow read above

    # -- Agile: the board and its sprints ------------------------------------------------------
    st, boards = pr.get("boards", "/rest/agile/1.0/board", {"projectKeyOrId": key})
    blist = rows(boards)
    f["boards"] = {"status": st, "rows": [pick(b, "id", "name", "type") for b in blist], "error": error(st, boards)}
    f["board_detail"] = {}
    for b in blist[:2]:
        bid = b.get("id")
        detail: dict = {}
        st, conf = pr.get(f"board {bid} configuration", f"/rest/agile/1.0/board/{bid}/configuration")
        if isinstance(conf, dict):
            detail["configuration"] = {
                **pick(conf, "type", "ranking", "estimation"),
                "filter": (conf.get("filter") or {}).get("id"),
                "columns": [{"name": c.get("name"), "statuses": [s.get("id") for s in c.get("statuses") or []]}
                            for c in (conf.get("columnConfig") or {}).get("columns") or []],
            }
        else:
            detail["configuration"] = {"status": st, "body": conf}
        st, bf = pr.get(f"board {bid} features", f"/rest/agile/1.0/board/{bid}/features")
        detail["features"] = [pick(x, "boardFeature", "feature", "state", "featureType") for x in
                              (bf.get("features") if isinstance(bf, dict) else []) or []] or {"status": st, "body": bf}
        st, sprints = pr.get(f"board {bid} sprints", f"/rest/agile/1.0/board/{bid}/sprint")
        detail["sprints"] = {"status": st, "error": error(st, sprints), "rows": [
            pick(s, "id", "name", "state", "startDate", "endDate", "completeDate", "originBoardId") for s in rows(sprints)]}
        st, bl = pr.get(f"board {bid} backlog", f"/rest/agile/1.0/board/{bid}/backlog", {"maxResults": 1})
        detail["backlog"] = {"status": st, "shape": summarize(bl), "error": error(st, bl)}
        f["board_detail"][str(bid)] = detail
    return f


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jira_phase5_readonly.py", description=__doc__.split("\n\n")[0])
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
    findings["rate_headers_seen"] = sorted(headers_seen)
    findings["call_log"] = log
    out = HERE / "jira-probe-report.json"
    out.write_text(json.dumps(findings, indent=2, default=str))
    print(f"\n{len(log)} calls, all GET; report → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
