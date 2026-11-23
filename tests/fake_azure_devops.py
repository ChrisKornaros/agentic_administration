"""A fake Azure DevOps pull-request endpoint: an `opener` for
`AzureDevOpsPullRequests`, never a socket. It serves the per-repository and
the per-project list from records, pages them by `$top` and `$skip`, and
records every request it saw. Shapes follow Microsoft's REST reference
(api-version 7.1), as `issues/azure_devops.py` cites it; no live
organization has been read."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from email.message import Message
from typing import Any

API = "https://dev.azure.test"
ORGANIZATION = "example-org"
PROJECT = "Example Project"  # a project's name may hold a space
REPO = "example-repo"
REPOSITORY = f"{PROJECT}/{REPO}"
TOKEN = "fake-token"
ROOT = f"/{ORGANIZATION}/{urllib.parse.quote(PROJECT)}"


def record(number: int, title: str, *, description: str | None = "", branch: str = "feature/x", repo: str = REPO,
           labels: tuple[str, ...] = (), inactive_labels: tuple[str, ...] = (), created: str = "2026-01-02T03:04:05.123Z",
           status: str = "active") -> dict[str, Any]:
    return {
        "pullRequestId": number, "title": title, "status": status, "isDraft": False, "creationDate": created,
        "sourceRefName": f"refs/heads/{branch}", "targetRefName": "refs/heads/main",
        "labels": [{"id": f"label-{n}", "name": n, "active": True} for n in labels]
                  + [{"id": f"label-{n}", "name": n, "active": False} for n in inactive_labels],
        "repository": {"id": f"repo-{repo}", "name": repo, "project": {"id": "project-1", "name": PROJECT}},
        "url": f"{API}{ROOT}/_apis/git/repositories/repo-{repo}/pullRequests/{number}",
        **({} if description is None else {"description": description[:400]}),
    }


class _Response:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body, self.status, self.headers = body.encode(), status, {"Content-Type": "application/json"}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class FakeAzureDevOps:
    def __init__(self, records: list[dict[str, Any]] | None = None, *, page_size: int = 100) -> None:
        self.records = list(records or [])
        self.page_size = page_size  # the most a page holds, whatever $top asks for
        self.requests: list[Any] = []  # every urllib Request, in order
        self.fail: tuple[int, str] | None = None  # (status, body): raised as an HTTPError
        self.answer: tuple[int, str] | None = None  # (status, body): returned as it is, as a 203 page would be

    def __call__(self, req, timeout: float = 0):
        self.requests.append(req)
        if self.fail:
            status, body = self.fail
            raise urllib.error.HTTPError(req.full_url, status, "error", Message(), io.BytesIO(body.encode()))
        if self.answer:
            return _Response(self.answer[1], self.answer[0])
        url = urllib.parse.urlsplit(req.full_url)
        query = dict(urllib.parse.parse_qsl(url.query))
        assert req.get_method() == "GET" and query["searchCriteria.status"] == "active" and query["api-version"], req.full_url
        rows = [r for r in self.records if r["status"] == "active"]
        if url.path == f"{ROOT}/_apis/git/repositories/{REPO}/pullrequests":
            rows = [r for r in rows if r["repository"]["name"] == REPO]
        else:
            assert url.path == f"{ROOT}/_apis/git/pullrequests", req.full_url
        rows.sort(key=lambda r: r["creationDate"], reverse=True)
        skip, top = int(query["$skip"]), min(int(query["$top"]), self.page_size)
        chunk = rows[skip: skip + top]
        return _Response(json.dumps({"value": chunk, "count": len(chunk)}))
