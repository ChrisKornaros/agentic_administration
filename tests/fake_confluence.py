"""A fake Confluence Cloud for the offline tests — never a live site.

Shapes follow the Phase 6b probe (probes/confluence_phase6b_readonly.py, run
2026-09-28 against a `knowledge_base` space): v2 lists answer `{results,
_links}` with `_links.base` the site's `/wiki`; a page row carries
`parentId`, `status` and `version`; v2 holds ADF as a JSON string in
`value`; a v1 search hit holds the page under `content`. `_links.next` is
under `/wiki` on v2 and relative to it on v1, as the docs say and the
conformance run (2026-09-28) saw. It pages small (`page_size`) so the
cursor walk is exercised.

Seen live by that run, with its error text: a title is unique in its space
(400), an archived page's too; the page listing includes archived pages;
a page update names the next version number (409); a PUT with a new
`parentId` moves the page; a property write leaves the page version alone.
Page ids are not in creation order, so a row carries `createdAt`. Still
as documented: titles clash case aside, a property update names its next
version too, a label holds no spaces, and CQL finds only current pages.
Ids are made up.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
import urllib.parse
from typing import Any

from adapters.base import NotFound, ValidationError

SITE = "https://example.atlassian.net"
BASE = f"{SITE}/wiki"
KEY, SPACE_ID, HOME = "KB", "3000", "3001"


class FakeConfluence:
    """One space, its pages, and a log of every call. Unknown routes raise `NotFound`."""

    def __init__(self, *, page_size: int = 2) -> None:
        self.page_size = page_size
        self.pages: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, dict, Any]] = []
        self.fail: dict[str, Exception] = {}  # "METHOD path" -> raise
        self._ids = itertools.count(4000)
        self.add_page("Knowledge base", parent=None, page_id=HOME)
        self.parent = self.add_page("Docs")["id"]  # the configured parent in the tests

    # -- helpers -----------------------------------------------------------------

    @property
    def log(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _, _ in self.calls]

    def writes(self, since: int = 0) -> list[tuple[str, str]]:
        return [(m, p) for m, p in self.log[since:] if m != "GET"]

    def add_page(self, title: str, parent: str | None = HOME, *, page_id: str | None = None,
                 labels: tuple[str, ...] = (), props: dict[str, Any] | None = None) -> dict[str, Any]:
        """Seed a page directly (no call logged)."""
        pid = page_id or str(next(self._ids))
        created = f"2026-09-28T12:{len(self.pages) // 60:02d}:{len(self.pages) % 60:02d}.000Z"
        self.pages[pid] = {"id": pid, "title": title, "parentId": parent, "status": "current", "createdAt": created,
                           "version": {"number": 1}, "value": json.dumps({"version": 1, "type": "doc", "content": []}),
                           "labels": set(labels), "properties": {}}
        for key, value in (props or {}).items():
            self._add_prop(pid, key, value)
        return self.pages[pid]

    def by_title(self, title: str) -> dict[str, Any]:
        return next(p for p in self.pages.values() if p["title"] == title)

    def doc(self, title: str) -> dict[str, Any]:
        return json.loads(self.by_title(title)["value"])

    def prop(self, title: str, key: str = "md-source") -> dict[str, Any]:
        return self.by_title(title)["properties"][key]

    def edit_in_ui(self, title: str) -> None:
        """Someone edits a page in Confluence: a new version, no property change."""
        self.by_title(title)["version"]["number"] += 1

    def _get(self, pid: str, where: str) -> dict[str, Any]:
        if pid not in self.pages:
            raise NotFound(f"HTTP 404 on {where}: Page not found")
        return self.pages[pid]

    def _row(self, p: dict[str, Any]) -> dict[str, Any]:
        return {"id": p["id"], "title": p["title"], "parentId": p["parentId"], "createdAt": p["createdAt"],
                "parentType": "page" if p["parentId"] else None, "status": p["status"], "spaceId": SPACE_ID,
                "version": dict(p["version"]), "_links": {"webui": f"/spaces/{KEY}/pages/{p['id']}"}}

    def _listing(self, path: str, rows: list[Any], params: dict[str, Any], *, relative: bool = False) -> dict[str, Any]:
        start = int(params.get("cursor") or 0)
        size = min(int(params.get("limit") or 25), self.page_size)
        out: dict[str, Any] = {"results": rows[start : start + size], "_links": {"base": BASE}}
        if start + size < len(rows):
            rest = {k: v for k, v in params.items() if k != "cursor"}
            nxt = f"{path}?{urllib.parse.urlencode({**rest, 'cursor': start + size})}"
            out["_links"]["next"] = nxt.removeprefix("/wiki") if relative else nxt
        return out

    def _title_free(self, title: str, pid: str | None, where: str) -> None:
        if any(p["title"].casefold() == title.casefold() and p["id"] != pid for p in self.pages.values()):
            raise ValidationError(f"HTTP 400 on {where}: A page with this title already exists: "
                                  f"A page already exists with the same TITLE in this space")

    def _check_body(self, body: Any, where: str) -> dict[str, Any]:
        if not isinstance(body, dict) or body.get("representation") != "atlas_doc_format" \
                or not isinstance(body.get("value"), str):
            raise ValidationError(f"HTTP 400 on {where}: body must be atlas_doc_format with a string value")
        doc = json.loads(body["value"])
        if doc.get("type") != "doc":
            raise ValidationError(f"HTTP 400 on {where}: not an ADF doc")
        return doc

    def _add_prop(self, pid: str, key: str, value: Any) -> dict[str, Any]:
        page = self.pages[pid]
        if key in page["properties"]:
            raise ValidationError(f"HTTP 409 on POST /wiki/api/v2/pages/{pid}/properties: key {key} already exists")
        prop = {"id": str(next(self._ids)), "key": key, "value": copy.deepcopy(value), "version": {"number": 1}}
        page["properties"][key] = prop
        return copy.deepcopy(prop)

    # -- routes ------------------------------------------------------------------

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        rows = [p for p in self.pages.values() if p["status"] == "current"]
        for clause in (params.get("cql") or "").split(" and "):
            m = re.fullmatch(r'(\w+)\s*=\s*"?([^"]*)"?', clause.strip())
            if not m:
                raise ValidationError(f"HTTP 400 on GET /wiki/rest/api/search: could not parse {clause!r}")
            name, value = m.groups()
            if name == "space":
                rows = rows if value == KEY else []
            elif name == "type":
                rows = rows if value == "page" else []
            elif name == "label":
                rows = [p for p in rows if value in p["labels"]]
            else:
                raise ValidationError(f"HTTP 400 on GET /wiki/rest/api/search: the fake does not know {clause!r}")
        hits = [{"content": {"id": p["id"], "type": "page", "status": p["status"], "title": p["title"]},
                 "title": p["title"], "url": f"/spaces/{KEY}/pages/{p['id']}", "excerpt": ""} for p in rows]
        return self._listing("/wiki/rest/api/search", hits, params, relative=True)

    def request(self, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
        split = urllib.parse.urlsplit(path)
        path, params = split.path, {**dict(urllib.parse.parse_qsl(split.query)), **(params or {})}
        self.calls.append((method, path, params, copy.deepcopy(body)))
        where = f"{method} {path}"
        if where in self.fail:
            raise self.fail[where]
        if method == "GET":
            if path == "/wiki/api/v2/spaces":
                space = {"id": SPACE_ID, "key": KEY, "name": "Knowledge", "type": "knowledge_base",
                         "status": "current", "homepageId": HOME, "_links": {"webui": f"/spaces/{KEY}"}}
                return {"results": [space] if params.get("keys") == KEY else [], "_links": {"base": BASE}}
            if path == f"/wiki/api/v2/spaces/{SPACE_ID}/pages":
                rows = [self._row(p) for p in self.pages.values() if params.get("status") in (None, p["status"])]
                return self._listing(path, rows, params)
            m = re.fullmatch(r"/wiki/api/v2/pages/(\d+)", path)
            if m:
                page = self._get(m.group(1), where)
                body = {"atlas_doc_format": {"representation": "atlas_doc_format", "value": page["value"]}}
                return {**self._row(page), "body": body if params.get("body-format") == "atlas_doc_format" else {}}
            if path == "/wiki/rest/api/search":
                return self._search(params)
            m = re.fullmatch(r"/wiki/api/v2/pages/(\d+)/properties", path)
            if m:
                props = self._get(m.group(1), where)["properties"].values()
                rows = [copy.deepcopy(p) for p in props if params.get("key") in (None, p["key"])]
                return self._listing(path, rows, params)
        if method == "POST":
            if path == "/wiki/api/v2/pages":
                b = body or {}
                if b.get("spaceId") != SPACE_ID or not (b.get("title") or "").strip():
                    raise ValidationError(f"HTTP 400 on {where}: spaceId and title are required")
                self._title_free(b["title"], None, where)
                self._get(b.get("parentId") or "", where)
                doc = self._check_body(b.get("body"), where)
                page = self.add_page(b["title"], b["parentId"])
                page["value"] = json.dumps(doc)
                return self._row(page)
            m = re.fullmatch(r"/wiki/rest/api/content/(\d+)/label", path)
            if m:
                page = self._get(m.group(1), where)
                for label in body or []:
                    if re.search(r"\s", label.get("name") or " "):
                        raise ValidationError(f"HTTP 400 on {where}: a label holds no spaces")
                    page["labels"].add(label["name"].lower())
                return {"results": [{"prefix": "global", "name": n} for n in sorted(page["labels"])]}
            m = re.fullmatch(r"/wiki/api/v2/pages/(\d+)/properties", path)
            if m:
                self._get(m.group(1), where)
                return self._add_prop(m.group(1), body["key"], body["value"])
        if method == "PUT":
            m = re.fullmatch(r"/wiki/api/v2/pages/(\d+)", path)
            if m:
                page, b = self._get(m.group(1), where), body or {}
                if str(b.get("id")) != page["id"]:
                    raise ValidationError(f"HTTP 400 on {where}: the id in the body does not match")
                current, given = page["version"]["number"], (b.get("version") or {}).get("number")
                if given != current + 1:
                    raise ValidationError(f"HTTP 409 on {where}: Version must be incremented when updating a page. "
                                          f"Current Version: [{current}]. Provided version: [{given}]")
                self._title_free(b.get("title") or "", page["id"], where)
                if b.get("parentId"):
                    self._get(b["parentId"], where)
                    page["parentId"] = b["parentId"]
                page["value"] = json.dumps(self._check_body(b.get("body"), where))
                page["title"], page["version"] = b["title"], {"number": b["version"]["number"]}
                return self._row(page)
            m = re.fullmatch(r"/wiki/api/v2/pages/(\d+)/properties/(\d+)", path)
            if m:
                page, b = self._get(m.group(1), where), body or {}
                prop = next((p for p in page["properties"].values() if p["id"] == m.group(2)), None)
                if prop is None:
                    raise NotFound(f"HTTP 404 on {where}: no such property")
                if (b.get("version") or {}).get("number") != prop["version"]["number"] + 1:
                    raise ValidationError(f"HTTP 409 on {where}: Version must be incremented")
                prop["value"], prop["version"] = copy.deepcopy(b["value"]), {"number": b["version"]["number"]}
                return copy.deepcopy(prop)
        raise NotFound(f"fake has no route for {where}")
