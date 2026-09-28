"""HTTP transport for Jira Cloud (REST v3 + Agile 1.0) — the only Jira file
that knows the wire.

From the Phase 5 probe and preflight (probes/README.md, 2026-09-27):

- Auth is Basic: the account email + an API token (a classic, unscoped
  token, against the site URL). Both are fetched lazily from the secrets
  boundary on the first request, never at construction, and never logged.
- A 401 is never retried: repeated failed logins put the account behind a
  CAPTCHA (`X-Seraph-LoginReason: AUTHENTICATION_DENIED`), after which the
  REST API refuses it until someone logs in through the browser.
- API-token traffic meets Jira's burst limit (`RateLimit-Policy:
  "jira-burst-based";q=100;w=1`); a 429 carries `Retry-After` and maps to
  `RateLimited`. Calls are paced `throttle` seconds apart regardless.
- Errors come back as `{"errorMessages": [...], "errors": {field: msg}}`.
  Confluence on the same site (Phase 6b rides this transport, D29) answers
  v2 errors as `{"errors": [{"status", "code", "title", "detail"}]}` and v1
  ones as `{"statusCode", "message"}`.
- Paginated reads answer `{startAt, maxResults, total?, isLast, values}`
  or a bare list; `get_all` walks both. Search pages by `nextPageToken`,
  which the adapter walks itself.

Errors never leave here as `urllib` exceptions — see `adapters.base`.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping, Protocol

from adapters.base import (
    AdapterError,
    AuthError,
    NotFound,
    RateLimited,
    TransportError,
    ValidationError,
)
from server.secrets import SecretUnavailable

USER_AGENT = (
    "agentic-administration/0.0 (jira adapter; "
    "+https://github.com/ChrisKornaros/agentic_administration)"
)
DEFAULT_THROTTLE = 0.5  # seconds between calls; far under the burst limit, human-paced per the AUP


class Transport(Protocol):
    """What the adapter needs; tests inject a fake with the same shape."""

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: Any = None) -> Any: ...

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> list[Any]: ...


def site_url(site: str) -> str:
    """`example.atlassian.net` or `https://example.atlassian.net/` → the URL."""
    site = site.strip().rstrip("/")
    return site if site.startswith(("https://", "http://")) else f"https://{site}"


class JiraTransport:
    def __init__(
        self,
        site: str,
        user: Callable[[], str],
        token: Callable[[], str],
        *,
        throttle: float = DEFAULT_THROTTLE,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.base_url = site_url(site)
        self._user, self._token = user, token
        self._auth: str | None = None
        self.throttle = throttle
        self.timeout = timeout
        self._sleep, self._clock, self._open = sleep, clock, opener
        self._last: float | None = None
        # (method, path) of every request sent, in order — what the
        # conformance suite audits for "no DELETE, ever"
        self.log: list[tuple[str, str]] = []

    @property
    def calls(self) -> int:
        return len(self.log)

    def _pace(self) -> None:
        now = self._clock()
        if self._last is not None:
            wait = self.throttle - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last = now

    def _authorization(self) -> str:
        if self._auth is None:
            try:
                pair = f"{self._user()}:{self._token()}"
            except SecretUnavailable as exc:
                raise AuthError(f"no Jira credentials: {exc}") from None
            self._auth = "Basic " + base64.b64encode(pair.encode()).decode()
        return self._auth

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: Any = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
        headers = {
            "Authorization": self._authorization(),
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, method=method, headers=headers, data=data)
        self._pace()
        self.log.append((method, path))
        try:
            with self._open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise _map_http_error(method, path, exc.code, exc.read().decode("utf-8", "replace"),
                                  exc.headers or {}) from None
        except urllib.error.URLError as exc:
            raise TransportError(f"could not reach Jira for {method} {path}: {exc.reason}") from None
        except TimeoutError:
            raise TransportError(f"timed out on {method} {path}") from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise TransportError(f"non-JSON answer to {method} {path}", detail=raw[:200]) from None

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        params = dict(params or {})
        params.setdefault("maxResults", 100)
        items: list[Any] = []
        while True:
            page = self.request("GET", path, params=params)
            if isinstance(page, list):
                return items + page
            if not isinstance(page, dict):
                return items
            values = page.get("values") or []
            items.extend(values)
            start = int(page.get("startAt") or 0) + len(values)
            total = page.get("total")
            if page.get("isLast", True) or not values or (total is not None and start >= int(total)):
                return items
            params["startAt"] = start


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def _map_http_error(method: str, path: str, status: int, raw: str, headers: Mapping[str, str]) -> AdapterError:
    """Vendor failure → the project's taxonomy. Jira error bodies never echo
    the Authorization header, so `detail` is safe."""
    where = f"{method} {path}"
    if 300 <= status < 400:
        return TransportError(f"HTTP {status} on {where}: redirected to {_header(headers, 'Location') or '(no Location)'}")
    message: str | None = None
    detail: str | None = None
    if raw and raw.lstrip()[:1] in ("{", "["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            parts = [str(m) for m in parsed.get("errorMessages") or []]
            errors = parsed.get("errors") or {}
            if isinstance(errors, dict):
                parts += [f"{k}: {v}" for k, v in errors.items()]
            else:  # Confluence v2: a list of {title, detail, code}
                parts += [" — ".join(str(e[k]) for k in ("title", "detail") if e.get(k)) or str(e.get("code") or e)
                          if isinstance(e, dict) else str(e) for e in errors]
            message = "; ".join(parts) or parsed.get("message") or None
            detail = json.dumps(parsed)[:500]
    elif raw:
        detail = raw[:200]
    if status == 401:
        if "AUTHENTICATION_DENIED" in (_header(headers, "X-Seraph-LoginReason") or ""):
            return AuthError(f"HTTP 401 on {where}: Jira wants a CAPTCHA after failed logins — log in once in "
                             "the browser, then check the email + API token", detail=detail)
        return AuthError(f"HTTP 401 on {where}: {message or 'the email + API token were refused'} "
                         "(not retried: repeated failures lock the account behind a CAPTCHA)", detail=detail)
    if status == 403:
        return AuthError(f"HTTP 403 on {where}: {message or 'not permitted'}", detail=detail)
    if status == 404:
        return NotFound(f"HTTP 404 on {where}: {message or 'not found'}", detail=detail)
    if status == 429:
        after = _header(headers, "Retry-After")
        return RateLimited(f"rate limited on {where}" + (f"; retry after {after}s" if after else ""), detail=detail)
    if status == 410:
        return TransportError(f"HTTP 410 on {where}: {message or 'this API was removed'}", detail=detail)
    if 400 <= status < 500:
        return ValidationError(f"HTTP {status} on {where}: {message or 'rejected'}", detail=detail)
    return TransportError(f"HTTP {status} on {where}: {message or 'server error'}", detail=detail)
