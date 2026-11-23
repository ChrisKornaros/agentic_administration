"""Azure DevOps' open pull requests over REST — the only file here that
knows that wire.

Azure Repos has no issue tracker of its own, so on this host the open items
a planner reads are a repository's **active pull requests**: an
`IssueSource` whose issues are pull requests.

**Read from Microsoft's REST reference on 2026-11-23, not from a live
organization** (api-version 7.1, Azure DevOps Services):

- `GET {api}/{organization}/{project}/_apis/git/repositories/{repository}/pullrequests`
  lists one repository's, and `GET {api}/{organization}/{project}/_apis/git/pullrequests`
  the whole project's. `searchCriteria.status=active` keeps the open ones.
  Paging is `$top` and `$skip`; the reference gives no default and no
  maximum, so both are always sent, the next page starts after however
  many came back, and the read ends on an empty page or at the limit.
- The answer is `{"value": [...], "count": n}`. Each entry carries
  `pullRequestId`, `title`, `description` (**cut to 400 characters in a
  list**), `sourceRefName` (`refs/heads/<branch>`), `creationDate`,
  `labels` (objects with a `name` and an `active` flag) and `repository`
  (with its `name`). Its `url` is the REST address, so the page a person
  opens is built here: `{api}/{organization}/{project}/_git/{repository}/pullrequest/{id}`.
- A list entry has no last-updated date. `updated` is the day the pull
  request was opened, and the read is ordered by that day, newest first.
- A personal access token goes as Basic auth with an empty user name; a
  Microsoft Entra token goes as a bearer token.
- A rate limit answers 429; a slowed request still answers 200.

**Not in the reference, from other users' reports:** a token Azure DevOps
does not accept can be answered with a redirect to a sign-in page, or with
203 and that page's HTML, instead of 401. So redirects are never followed
(the token goes nowhere but the configured host), `X-TFS-FedAuthRedirect:
Suppress` asks for a plain 401, and a redirect, a 203 or an answer that is
not JSON is an `AuthError`.

A board key is looked for in a pull request's title, its source branch and
its description, in that order: they are the lines of `Issue.body`. A key
that sits past the description's first 400 characters is not seen.

Only GET is sent. Errors leave as `adapters.base` errors, never as `urllib`
ones.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from adapters.base import AdapterError, AuthError, NotFound, RateLimited, TransportError
from issues.source import Issue
from server.secrets import SecretUnavailable

USER_AGENT = "agentic-administration (open pull requests; +https://github.com/ChrisKornaros/agentic_administration)"
API_VERSION = "7.1"
PER_PAGE = 100
EVERY_REPOSITORY = "*"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a redirect then surfaces as an HTTPError, and the token is not sent on


_OPEN = urllib.request.build_opener(_NoRedirect).open


def _error(status: int, raw: str, where: str) -> AdapterError:
    try:
        message = str(json.loads(raw).get("message") or "")
    except (json.JSONDecodeError, AttributeError):
        message = ""
    if status in (401, 403):
        return AuthError(f"the code host refused the token for {where} (HTTP {status}: {message or 'no message'})")
    if status == 203 or 300 <= status < 400:
        return AuthError(f"the code host answered with a sign-in page (HTTP {status}): it does not accept the token")
    if status == 404:
        return NotFound(f"{where} was not found, or the token cannot read it")
    if status == 429:
        return RateLimited("the code host is rate-limiting (HTTP 429)")
    return TransportError(f"HTTP {status} from the code host", detail=raw[:200])


class AzureDevOpsPullRequests:
    """An `IssueSource` over one repository's active pull requests, or one project's."""

    def __init__(self, api: str, organization: str, repository: str, token: Callable[[], str], *, auth: str = "pat",
                 timeout: float = 30.0, opener: Callable[..., Any] = _OPEN) -> None:
        self.project, _, self.repository = repository.partition("/")
        self.where = f"{organization}/{repository}"
        self._root = f"{api.rstrip('/')}/{urllib.parse.quote(organization, safe='')}/{urllib.parse.quote(self.project, safe='')}"
        self._token, self._auth, self._timeout, self._open = token, auth, timeout, opener
        self.log: list[tuple[str, str]] = []  # (method, URL) of every request sent, in order

    def _authorization(self) -> str:
        try:
            token = self._token()
        except SecretUnavailable as exc:
            raise AuthError(f"no token for the code host: {exc}") from None
        if self._auth == "bearer":
            return f"Bearer {token}"
        return "Basic " + base64.b64encode(f":{token}".encode()).decode()

    def _get(self, url: str) -> Any:
        req = urllib.request.Request(url, method="GET", headers={
            "Authorization": self._authorization(), "Accept": "application/json",
            "X-TFS-FedAuthRedirect": "Suppress", "User-Agent": USER_AGENT})
        self.log.append(("GET", url))
        try:
            with self._open(req, timeout=self._timeout) as resp:
                status, raw = getattr(resp, "status", 200), resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise _error(exc.code, exc.read().decode("utf-8", "replace"), self.where) from None
        except urllib.error.URLError as exc:
            raise TransportError(f"could not reach the code host: {exc.reason}") from None
        except TimeoutError:
            raise TransportError("the code host timed out") from None
        if status != 200:
            raise _error(status, raw, self.where)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if raw.lstrip()[:1] == "<":
                raise AuthError("the code host answered with a page, not JSON: it does not accept the token") from None
            raise TransportError("the code host's answer was not JSON", detail=raw[:200]) from None

    def _page(self, skip: int) -> list[Any]:
        scope = "" if self.repository == EVERY_REPOSITORY else f"/repositories/{urllib.parse.quote(self.repository, safe='')}"
        query = urllib.parse.urlencode({"searchCriteria.status": "active", "$top": PER_PAGE, "$skip": skip,
                                        "api-version": API_VERSION})
        answer = self._get(f"{self._root}/_apis/git{scope}/pullrequests?{query}")
        if not isinstance(answer, dict) or not isinstance(answer.get("value"), list):
            raise TransportError("the code host's answer was not a list of pull requests")
        return answer["value"]

    def _issue(self, rec: dict[str, Any]) -> Issue:
        number = int(rec["pullRequestId"])
        repository = str((rec.get("repository") or {}).get("name") or self.repository)
        title = str(rec.get("title") or "")
        branch = str(rec.get("sourceRefName") or "").removeprefix("refs/heads/")
        return Issue(
            number=number, title=title,
            url=f"{self._root}/_git/{urllib.parse.quote(repository, safe='')}/pullrequest/{number}",
            labels=tuple(str(lb["name"]) for lb in rec.get("labels") or ()
                         if isinstance(lb, dict) and lb.get("name") and lb.get("active", True)),
            updated=str(rec.get("creationDate") or "")[:10],
            body="\n".join((title, branch, str(rec.get("description") or ""))))

    def open_issues(self, limit: int) -> list[Issue]:
        found: list[Issue] = []
        skip = 0
        while len(found) < limit:
            page = self._page(skip)
            if not page:
                break
            found += [self._issue(rec) for rec in page if isinstance(rec, dict) and rec.get("pullRequestId") is not None]
            skip += len(page)
        found.sort(key=lambda i: (i.updated, i.number), reverse=True)
        return found[:limit]
