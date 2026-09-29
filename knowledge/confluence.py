"""Confluence Cloud over REST — the only knowledge file that knows the wire
(design: agentic_optimization_research roadmap/14 D26–D29).

From the Phase 6b probe (probes/README.md, 2026-09-28):

- The classic Jira token and the account email work as Basic auth under
  `/wiki` on the same site (D29), so this rides `adapters.jira.transport`:
  its throttle, its 429 → `RateLimited` (no rate-limit headers came back at
  all), its request log, its error taxonomy.
- v2 lists answer `{results, _links}`, and `_links.base` is `<site>/wiki`,
  the root a page's web URL hangs off. A page listing carries each page's
  `parentId` and `version`.
- v2 carries an ADF body as a JSON *string* in `value`.
- CQL (v1 `/rest/api/search`) finds pages by label, and an absent label
  answers 200 and empty. A hit holds the page under `content`.
- `_links.next` pages a listing: a path under `/wiki` on v2, and relative
  to it on v1 (`/rest/api/search?next=true&cursor=…`), as the docs say and
  the conformance run (2026-09-28) saw; `_walk` takes either.
- Labels are written through v1 (`POST /content/{id}/label`); content
  properties through v2.
- The read side (a read-only check on `AGKB`, 2026-09-28): `siteSearch ~`
  ranks its hits and matched a question ("how do I set up"), where `text ~`
  scored every hit 0 and found nothing for that question. A hit's `title` and
  `excerpt` carry `@@@hl@@@…@@@endhl@@@` around the matched words;
  `content.title` is the plain title; `breadcrumbs` came back empty. A
  query's quotes, escaped, and its brackets and hyphens answer 200.

No delete: the classic token *can* delete (D29), so the no-delete rule is
held here, in code. There is no DELETE request in this file, and
tests/test_knowledge.py fails if one appears.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from adapters.base import NotFound
from adapters.jira.transport import Transport

WIKI = "/wiki"


@dataclass(frozen=True)
class Space:
    id: str
    key: str
    homepage_id: str
    base: str  # `<site>/wiki`

    def page_url(self, page_id: str) -> str:
        return f"{self.base}/spaces/{self.key}/pages/{page_id}"


def _body(doc: dict[str, Any]) -> dict[str, str]:
    return {"representation": "atlas_doc_format", "value": json.dumps(doc)}


def cql_string(value: str) -> str:
    """A CQL string literal: in double quotes, with `\\` and `"` escaped."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def page_version(record: Any, default: int = 1) -> int:
    """The `version.number` of a page or property record."""
    return int(((record or {}).get("version") or {}).get("number") or default)


class Confluence:
    def __init__(self, transport: Transport) -> None:
        self.t = transport

    def _walk(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Every row of a `results` listing, following `_links.next`."""
        rows: list[dict[str, Any]] = []
        page = self.t.request("GET", path, params=params)
        while True:
            rows += (page or {}).get("results") or []
            nxt = ((page or {}).get("_links") or {}).get("next")
            if not nxt:
                return rows
            page = self.t.request("GET", nxt if nxt.startswith(WIKI + "/") else WIKI + nxt)

    # -- reads ---------------------------------------------------------------------------

    def space(self, key: str) -> Space:
        page = self.t.request("GET", f"{WIKI}/api/v2/spaces", params={"keys": key}) or {}
        rows = page.get("results") or []
        if not rows:
            raise NotFound(f"no space with key {key!r}, or no permission to see it")
        s = rows[0]
        base = str((page.get("_links") or {}).get("base") or "").rstrip("/")
        return Space(str(s["id"]), str(s.get("key") or key), str(s.get("homepageId") or ""), base)

    def pages(self, space_id: str) -> list[dict[str, Any]]:
        """Every page in the space: id, title, parentId, version, status."""
        return self._walk(f"{WIKI}/api/v2/spaces/{space_id}/pages", {"limit": 250})

    def labelled(self, space_key: str, label: str) -> list[str]:
        """The ids of the space's pages carrying `label`, by CQL (the search index, so it can lag a write)."""
        cql = f'space = "{space_key}" and type = page and label = "{label}"'
        hits = self._walk(f"{WIKI}/rest/api/search", {"cql": cql, "limit": 100})
        return [str(h["content"]["id"]) for h in hits if (h.get("content") or {}).get("id")]

    def page(self, page_id: str) -> dict[str, Any]:
        """One page with its body, parsed from v2's JSON string into `doc` (None when it has none)."""
        record = self.t.request("GET", f"{WIKI}/api/v2/pages/{page_id}", params={"body-format": "atlas_doc_format"}) or {}
        value = ((record.get("body") or {}).get("atlas_doc_format") or {}).get("value")
        return {**record, "doc": json.loads(value) if value else None}

    def property(self, page_id: str, key: str) -> dict[str, Any] | None:
        rows = self._walk(f"{WIKI}/api/v2/pages/{page_id}/properties", {"key": key})
        return next((r for r in rows if r.get("key") == key), None)

    def labels(self, page_id: str) -> set[str]:
        return {str(r.get("name")) for r in self._walk(f"{WIKI}/api/v2/pages/{page_id}/labels", {"limit": 250})}

    def search(self, space_key: str, label: str, text: str, limit: int) -> list[dict[str, Any]]:
        """The first `limit` pages of the space carrying `label` that match `text`, best
        first: one call, no walk. Each hit is v1's, with the page under `content`."""
        cql = (f"space = {cql_string(space_key)} and type = page and label = {cql_string(label)}"
               f" and siteSearch ~ {cql_string(text)}")
        return (self.t.request("GET", f"{WIKI}/rest/api/search", params={"cql": cql, "limit": limit}) or {}) \
            .get("results") or []

    # -- writes: create and update only ---------------------------------------------------

    def create_page(self, space_id: str, parent_id: str, title: str, doc: dict[str, Any]) -> dict[str, Any]:
        return self.t.request("POST", f"{WIKI}/api/v2/pages", body={
            "spaceId": space_id, "status": "current", "title": title, "parentId": parent_id, "body": _body(doc)})

    def update_page(self, page_id: str, parent_id: str, title: str, doc: dict[str, Any],
                    version: int) -> dict[str, Any]:
        """`version` is the new number: the page's current one + 1."""
        return self.t.request("PUT", f"{WIKI}/api/v2/pages/{page_id}", body={
            "id": page_id, "status": "current", "title": title, "parentId": parent_id, "body": _body(doc),
            "version": {"number": version, "message": "Published from git"}})

    def add_labels(self, page_id: str, labels: list[str]) -> None:
        self.t.request("POST", f"{WIKI}/rest/api/content/{page_id}/label",
                       body=[{"prefix": "global", "name": name} for name in labels])

    def set_property(self, page_id: str, key: str, value: Any, current: dict[str, Any] | None) -> dict[str, Any]:
        """Create the property, or update `current` (as `property()` read it) at its version + 1."""
        if current is None:
            return self.t.request("POST", f"{WIKI}/api/v2/pages/{page_id}/properties", body={"key": key, "value": value})
        return self.t.request("PUT", f"{WIKI}/api/v2/pages/{page_id}/properties/{current['id']}", body={
            "key": key, "value": value, "version": {"number": page_version(current) + 1}})
