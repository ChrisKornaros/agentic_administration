"""GitHub's issues over REST — the only issues file that knows the wire.

Read on 2026-11-15 from `GET /repos/{owner}/{repo}/issues` on a public
repository:

- The answer is a JSON array, empty when nothing matches. `state=open`,
  `sort=updated` and `direction=desc` are query parameters; `per_page` goes
  to 100.
- **A pull request is in the list too**, marked by a `pull_request` key. An
  issue has none.
- Each entry carries `number`, `title`, `html_url`, `updated_at`
  (`2026-11-11T19:51:58Z`), `body` (a string, or null when empty) and
  `labels` (objects with a `name`).
- The next page is the `Link` header's `rel="next"` URL, taken whole.
- `X-RateLimit-Remaining` and `X-RateLimit-Reset` come back on every answer.
- A repository that does not exist answers 404 with `{"message": "Not
  Found"}`. GitHub's documentation says a private repository the token
  cannot read answers the same 404, and that a rate limit answers 403 or 429
  with `X-RateLimit-Remaining: 0` or a `Retry-After`; neither was seen here.

Only GET is sent. Errors leave as `adapters.base` errors, never as `urllib`
ones.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

from adapters.base import AdapterError, AuthError, NotFound, RateLimited, TransportError
from issues.source import Issue
from server.secrets import SecretUnavailable

USER_AGENT = "agentic-administration (open issues; +https://github.com/ChrisKornaros/agentic_administration)"
API_VERSION = "2022-11-28"
PER_PAGE = 100
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def _error(status: int, raw: str, headers: Mapping[str, str], repository: str) -> AdapterError:
    try:
        message = str(json.loads(raw).get("message") or "")
    except (json.JSONDecodeError, AttributeError):
        message = ""
    if status == 401:
        return AuthError(f"the code host refused the token (HTTP 401: {message or 'no message'})")
    limited = _header(headers, "X-RateLimit-Remaining") == "0" or _header(headers, "Retry-After") is not None
    if status == 429 or (status == 403 and limited):
        return RateLimited(f"the code host is rate-limiting (HTTP {status})")
    if status == 403:
        return AuthError(f"the token may not read {repository}'s issues (HTTP 403: {message or 'no message'})")
    if status == 404:
        return NotFound(f"{repository} was not found, or the token cannot read it")
    return TransportError(f"HTTP {status} from the code host", detail=raw[:200])


class GitHubIssues:
    """An `IssueSource` over one repository."""

    def __init__(self, api: str, repository: str, token: Callable[[], str], *, timeout: float = 30.0,
                 opener: Callable[..., Any] = urllib.request.urlopen) -> None:
        self.api, self.repository = api.rstrip("/"), repository
        self._token, self._timeout, self._open = token, timeout, opener
        self.log: list[tuple[str, str]] = []  # (method, URL) of every request sent, in order

    def _get(self, url: str) -> tuple[Any, str | None]:
        try:
            token = self._token()
        except SecretUnavailable as exc:
            raise AuthError(f"no token for the code host: {exc}") from None
        req = urllib.request.Request(url, method="GET", headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION, "User-Agent": USER_AGENT})
        self.log.append(("GET", url))
        try:
            with self._open(req, timeout=self._timeout) as resp:
                raw, link = resp.read().decode("utf-8"), _header(resp.headers, "Link")
        except urllib.error.HTTPError as exc:
            raise _error(exc.code, exc.read().decode("utf-8", "replace"), exc.headers or {}, self.repository) from None
        except urllib.error.URLError as exc:
            raise TransportError(f"could not reach the code host: {exc.reason}") from None
        except TimeoutError:
            raise TransportError("the code host timed out") from None
        try:
            return json.loads(raw), link
        except json.JSONDecodeError:
            raise TransportError("the code host's answer was not JSON", detail=raw[:200]) from None

    def open_issues(self, limit: int) -> list[Issue]:
        query = urllib.parse.urlencode({"state": "open", "sort": "updated", "direction": "desc", "per_page": PER_PAGE})
        url: str | None = f"{self.api}/repos/{self.repository}/issues?{query}"
        found: list[Issue] = []
        while url and len(found) < limit:
            page, link = self._get(url)
            if not isinstance(page, list):
                raise TransportError("the code host's answer was not a list of issues")
            for rec in page:
                if isinstance(rec, dict) and "pull_request" not in rec and len(found) < limit:
                    found.append(Issue(
                        number=int(rec["number"]), title=str(rec.get("title") or ""), url=str(rec.get("html_url") or ""),
                        labels=tuple(str(lb["name"]) for lb in rec.get("labels") or () if isinstance(lb, dict) and lb.get("name")),
                        updated=str(rec.get("updated_at") or "")[:10], body=str(rec.get("body") or "")))
            nxt = _NEXT.search(link or "")
            url = nxt.group(1) if nxt and page else None
            if url and not url.startswith(self.api + "/"):  # the token goes nowhere but the configured host
                raise TransportError("the code host pointed the next page at another host")
        return found
