"""A fake GitHub issues endpoint: an `opener` for `GitHubIssues`, never a
socket. It serves `GET /repos/{owner}/{repo}/issues` from a list of records,
pages them with a `Link` header, and records every request it saw."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from email.message import Message
from typing import Any

API = "https://api.github.test"
REPOSITORY = "example-org/example-repo"
TOKEN = "fake-token"


def record(number: int, title: str, *, body: str | None = "", labels: tuple[str, ...] = (), updated: str = "2026-01-02T03:04:05Z",
           pull_request: bool = False, state: str = "open") -> dict[str, Any]:
    rec: dict[str, Any] = {
        "number": number, "title": title, "state": state, "body": body, "updated_at": updated,
        "html_url": f"https://github.test/{REPOSITORY}/{'pull' if pull_request else 'issues'}/{number}",
        "labels": [{"name": name, "color": "ededed"} for name in labels],
    }
    if pull_request:
        rec["pull_request"] = {"url": f"{API}/repos/{REPOSITORY}/pulls/{number}"}
    return rec


class _Response:
    def __init__(self, body: str, headers: dict[str, str]) -> None:
        self._body, self.headers = body.encode(), headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class FakeGitHub:
    def __init__(self, records: list[dict[str, Any]] | None = None, *, page_size: int = 100) -> None:
        self.records = list(records or [])
        self.page_size = page_size
        self.requests: list[Any] = []  # every urllib Request, in order
        self.fail: tuple[int, dict[str, str], str] | None = None  # (status, headers, body) for the next request
        self.next_host: str | None = None  # point the next page somewhere else

    def __call__(self, req, timeout: float = 0):
        self.requests.append(req)
        if self.fail:
            status, headers, body = self.fail
            msg = Message()
            for k, v in headers.items():
                msg[k] = v
            raise urllib.error.HTTPError(req.full_url, status, "error", msg, io.BytesIO(body.encode()))
        url = urllib.parse.urlsplit(req.full_url)
        assert req.get_method() == "GET" and url.path == f"/repos/{REPOSITORY}/issues", req.full_url
        query = dict(urllib.parse.parse_qsl(url.query))
        assert query["state"] == "open"
        rows = sorted((r for r in self.records if r["state"] == "open"), key=lambda r: r["updated_at"], reverse=True)
        page = int(query.get("page", 1))
        size = min(int(query["per_page"]), self.page_size)
        chunk = rows[(page - 1) * size: page * size]
        headers = {"Content-Type": "application/json"}
        if page * size < len(rows):
            nxt = urllib.parse.urlencode({**query, "page": page + 1})
            headers["Link"] = f'<{self.next_host or API}{url.path}?{nxt}>; rel="next"'
        return _Response(json.dumps(chunk), headers)
