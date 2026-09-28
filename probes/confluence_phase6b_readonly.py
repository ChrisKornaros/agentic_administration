"""Phase 6b — read-only probe of Confluence Cloud (REST v2 + the v1 search/label routes).

The live check that gates the Markdown → Confluence publisher (roadmap/14
§9 Phase 6b, D26–D29): whether the API answers on this site's plan with the
classic Jira token (D29), what the space is and what its template put in it,
how pages nest and link (ids, `_links`, the web base URL an ADF link needs),
which ADF node types a real page holds and whether `adapters.jira.adf`
reads them back, whether labels and content properties read on a page, and
whether CQL answers the two lookups the design leans on: `label =` (finding
a published page again) and `text ~` (`search_docs`, D27). Findings go to
the design repo (agentic_optimization_research roadmap/14); this file is
the evidence of *how* they were read.

Every call is a GET — nothing is written. The token and the account email
come from the secrets boundary (`server/secrets.py`): `JIRA_API_TOKEN` and
`JIRA_USER`, the same classic token as the Jira adapter (D29), each an env
var or a Bitwarden item via `<NAME>_BW_ITEM`. Neither is printed. Throttled
~1 s/call. Stdlib only.

Usage:
  uv run python probes/confluence_phase6b_readonly.py --plan    # call list, no network
  CONFLUENCE_SITE=https://<site>.atlassian.net CONFLUENCE_SPACE=<KEY> \\
  JIRA_API_TOKEN_BW_ITEM=<item> JIRA_USER_BW_ITEM=<item> JIRA_USER_BW_FIELD=username \\
  BW_SESSION=... uv run python probes/confluence_phase6b_readonly.py
  # writes confluence-probe-report.json next to this file (space content — gitignored)
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
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from adapters.jira import adf  # noqa: E402  (does the Jira-side reader cope with Confluence's ADF?)
from server import secrets  # noqa: E402  (the one secret boundary)

THROTTLE = 1.0
USER_AGENT = "agentic-administration/0.0 (confluence probe; +https://github.com/ChrisKornaros/agentic_administration)"
# response headers worth keeping: the rate-limit surface
KEEP_HEADERS = re.compile(r"ratelimit|retry-after|x-arequestid|beta-", re.I)
NO_SUCH_LABEL = "agadm-probe-no-such-label"  # a label lookup that must come back empty, not fail

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
        for env in ("results", "values"):
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
        for env in ("results", "values"):
            if isinstance(body.get(env), list):
                return body[env]
    return body if isinstance(body, list) else []


def error(status: int, body: object) -> object:
    return None if status == 200 else body


def pick(d: object, *keys: str) -> dict:
    return {k: d.get(k) for k in keys} if isinstance(d, dict) else {}


def adf_census(doc: object) -> dict:
    """Which node types and marks an ADF document uses, and how often; no text."""
    nodes: Counter = Counter()
    marks: Counter = Counter()

    def walk(n: object) -> None:
        if isinstance(n, dict):
            nodes[n.get("type")] += 1
            for m in n.get("marks") or []:
                marks[m.get("type")] += 1
            for c in n.get("content") or []:
                walk(c)

    walk(doc)
    return {"nodes": dict(nodes), "marks": dict(marks)}


def plan_calls(space: str) -> list[str]:
    return [
        "GET /wiki/rest/api/user/current                      (auth works on /wiki with the classic token)",
        "GET /_edge/tenant_info                               (cloudId, for a scoped token later)",
        f"GET /wiki/api/v2/spaces?keys={space}                     (id, type, status, homepageId)",
        f"GET /wiki/rest/api/space/{space}?expand=homepage,metadata.labels   (v1 type / template signal)",
        "GET /wiki/api/v2/spaces/{id}/properties",
        "GET /wiki/api/v2/spaces/{id}/pages?depth=all&limit=250   (the template's tree: titles, parents, status)",
        "GET /wiki/api/v2/pages/{home}?body-format=atlas_doc_format&include-labels&include-properties&include-version",
        "GET /wiki/api/v2/pages/{home}?body-format=storage   (both representations answer?)",
        "GET /wiki/api/v2/pages/{home}/direct-children  +  /children",
        "GET /wiki/api/v2/pages/{home}/labels  +  /properties",
        "GET /wiki/rest/api/content/{home}/label              (v1: the label write route's read side)",
        "GET /wiki/api/v2/pages?space-id={id}&title=<home title>   (exact title lookup)",
        f"GET /wiki/rest/api/search?cql=space=\"{space}\" and type=page      (CQL envelope, paging)",
        f"GET /wiki/rest/api/search?cql=... and label=\"{NO_SUCH_LABEL}\"   (empty, not an error)",
        "GET /wiki/rest/api/search?cql=... and text ~ \"<word>\"   (full text: search_docs)",
        "GET /wiki/rest/api/search?cql=... and siteSearch ~ \"<word>\"   (the newer ranked search)",
    ]


def probe(pr: Probe, key: str) -> dict:
    f: dict = {"site": pr.site, "space_key": key}

    st, me = pr.get("user/current", "/wiki/rest/api/user/current")
    f["myself"] = {"status": st, **pick(me, "type", "accountType", "timeZone", "locale"),
                   "has_account_id": isinstance(me, dict) and bool(me.get("accountId"))}
    if st != 200:
        f["myself"]["body"] = me
        return f  # auth or product access failed: nothing else will answer
    st, tenant = pr.get("tenant_info", "/_edge/tenant_info")
    f["tenant"] = {"status": st, "has_cloud_id": isinstance(tenant, dict) and bool(tenant.get("cloudId"))}

    # -- the space ---------------------------------------------------------------------
    st, spaces = pr.get("space (v2, by key)", "/wiki/api/v2/spaces", {"keys": key})
    found = rows(spaces)
    if st != 200 or not found:
        f["space"] = {"status": st, "body": spaces}
        return f
    space = found[0]
    sid = str(space.get("id"))
    home = str(space.get("homepageId") or "")
    f["space"] = {**pick(space, "id", "key", "name", "type", "status", "authorId", "createdAt", "homepageId",
                         "currentActiveAlias", "spaceOwnerId"),
                  "record_keys": sorted(space), "links": (space.get("_links") or {}),
                  "envelope_links": (spaces.get("_links") if isinstance(spaces, dict) else None)}
    st, v1 = pr.get("space (v1)", f"/wiki/rest/api/space/{key}", {"expand": "homepage,metadata.labels"})
    f["space_v1"] = {"status": st, **pick(v1, "id", "key", "type", "status"),
                     "record_keys": sorted(v1) if isinstance(v1, dict) else None,
                     "labels": [pick(x, "prefix", "name") for x in
                                rows(((v1 or {}).get("metadata") or {}).get("labels") if isinstance(v1, dict) else None)],
                     "error": error(st, v1)}
    st, sprops = pr.get("space properties", f"/wiki/api/v2/spaces/{sid}/properties")
    f["space_properties"] = {"status": st, "keys": [p.get("key") for p in rows(sprops)], "error": error(st, sprops)}

    # -- the pages the template made -----------------------------------------------------
    st, pages = pr.get("space pages (all depths)", f"/wiki/api/v2/spaces/{sid}/pages", {"depth": "all", "limit": 250})
    plist = rows(pages)
    titles = Counter(p.get("title") for p in plist)
    f["pages"] = {"status": st, "count": len(plist), "more": bool(((pages or {}).get("_links") or {}).get("next"))
                  if isinstance(pages, dict) else None,
                  "rows": [pick(p, "id", "title", "status", "parentId", "parentType", "position", "authorId")
                           for p in plist],
                  "duplicate_titles": sorted(t for t, n in titles.items() if n > 1),
                  "item_keys": sorted(plist[0]) if plist else None, "error": error(st, pages)}
    if not home:
        f["homepage"] = None
        return f

    # -- one page, read every way the publisher will ------------------------------------
    st, page = pr.get("homepage (ADF)", f"/wiki/api/v2/pages/{home}", {
        "body-format": "atlas_doc_format", "include-labels": "true", "include-properties": "true",
        "include-version": "true"})
    hp: dict = {"status": st, **pick(page, "id", "title", "status", "parentId", "parentType", "spaceId"),
                "record_keys": sorted(page) if isinstance(page, dict) else None,
                "links": (page.get("_links") if isinstance(page, dict) else None),
                "version": pick((page or {}).get("version") if isinstance(page, dict) else None,
                                "number", "minorEdit", "createdAt")}
    body = ((page or {}).get("body") or {}).get("atlas_doc_format") if isinstance(page, dict) else None
    if isinstance(body, dict):
        hp["adf_body_keys"] = sorted(body)
        raw = body.get("value")
        hp["adf_value_type"] = type(raw).__name__  # the docs say a JSON string, not an object
        doc = json.loads(raw) if isinstance(raw, str) else raw
        hp["adf_census"] = adf_census(doc)
        try:
            md = adf.to_markdown(doc)
            hp["to_markdown"] = {"ok": True, "chars": len(md), "lines": md.count("\n") + 1}
        except Exception as exc:  # noqa: BLE001 — the finding is the failure itself
            hp["to_markdown"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    f["homepage"] = hp
    st, sto = pr.get("homepage (storage)", f"/wiki/api/v2/pages/{home}", {"body-format": "storage"})
    sbody = ((sto or {}).get("body") or {}).get("storage") if isinstance(sto, dict) else None
    f["homepage_storage"] = {"status": st, "has_body": isinstance(sbody, dict) and bool(sbody.get("value")),
                             "macros": sorted(set(re.findall(r'ac:name="([^"]+)"', (sbody or {}).get("value") or "")))
                             if isinstance(sbody, dict) else None}
    for route in ("direct-children", "children"):
        st, kids = pr.get(f"homepage {route}", f"/wiki/api/v2/pages/{home}/{route}")
        f[f"homepage_{route.replace('-', '_')}"] = {"status": st, "count": len(rows(kids)),
                                                    "item_keys": sorted(rows(kids)[0]) if rows(kids) else None,
                                                    "error": error(st, kids)}
    st, labels = pr.get("homepage labels (v2)", f"/wiki/api/v2/pages/{home}/labels")
    f["homepage_labels_v2"] = {"status": st, "rows": [pick(x, "prefix", "name") for x in rows(labels)],
                               "error": error(st, labels)}
    st, props = pr.get("homepage properties", f"/wiki/api/v2/pages/{home}/properties")
    f["homepage_properties"] = {"status": st, "keys": [p.get("key") for p in rows(props)], "error": error(st, props)}
    st, labels1 = pr.get("homepage labels (v1)", f"/wiki/rest/api/content/{home}/label")
    f["homepage_labels_v1"] = {"status": st, "shape": summarize(labels1), "error": error(st, labels1)}
    title = (page or {}).get("title") if isinstance(page, dict) else None
    if title:
        st, byt = pr.get("pages by exact title", "/wiki/api/v2/pages", {"space-id": sid, "title": title})
        f["title_lookup"] = {"status": st, "count": len(rows(byt)), "ids": [p.get("id") for p in rows(byt)],
                             "error": error(st, byt)}

    # -- CQL: the two lookups the design leans on ------------------------------------------
    scope = f'space = "{key}" and type = page'
    word = next((w for w in re.findall(r"[A-Za-z]{4,}", title or "")), "page")
    for name, cql in (("cql space pages", scope),
                      ("cql label (absent)", f'{scope} and label = "{NO_SUCH_LABEL}"'),
                      ("cql text", f'{scope} and text ~ "{word}"'),
                      ("cql siteSearch", f'{scope} and siteSearch ~ "{word}"')):
        st, res = pr.get(name, "/wiki/rest/api/search", {"cql": cql, "limit": 5})
        hits = rows(res)
        f[name.replace(" ", "_").replace("(", "").replace(")", "")] = {
            "cql": cql, "status": st, "shape": summarize(res),
            "total": (res or {}).get("totalSize") if isinstance(res, dict) else None,
            "hit_keys": sorted(hits[0]) if hits else None,
            "hit_content_keys": sorted(hits[0].get("content") or {}) if hits and isinstance(hits[0], dict) else None,
            "error": error(st, res)}
    return f


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="confluence_phase6b_readonly.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--site", default=os.environ.get("CONFLUENCE_SITE"),
                        help="https://<site>.atlassian.net (or CONFLUENCE_SITE)")
    parser.add_argument("--space", default=os.environ.get("CONFLUENCE_SPACE"), help="space key (or CONFLUENCE_SPACE)")
    parser.add_argument("--plan", action="store_true", help="print the call list; no network")
    args = parser.parse_args(argv)
    if args.plan:
        print("\n".join(plan_calls(args.space or "<KEY>")))
        return 0
    if not (args.site and args.space):
        parser.error("--site and --space (or CONFLUENCE_SITE / CONFLUENCE_SPACE) are required")
    try:
        pr = Probe(args.site, secrets.get("JIRA_USER"), secrets.get("JIRA_API_TOKEN"))
    except secrets.SecretUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = probe(pr, args.space)
    findings["rate_headers_seen"] = sorted(headers_seen)
    findings["call_log"] = log
    out = HERE / "confluence-probe-report.json"
    out.write_text(json.dumps(findings, indent=2, default=str))
    print(f"\n{len(log)} calls, all GET; report → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
