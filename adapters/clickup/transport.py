"""HTTP transport for ClickUp's public API (v2): the only ClickUp file that
knows the wire.

From the Phase 8 probe (probes/clickup_phase8_readonly.py, run 2026-11-23
on a paid-plan workspace):

- A personal token (`pk_…`) is the whole `Authorization` header, with no
  `Bearer`. It is fetched lazily from the secrets boundary on the first
  request, never at construction, and never logged.
- The limit is per minute and per token: `X-RateLimit-Limit` read 1000
  there (ClickUp documents 100 on Free), and a 429 maps to `RateLimited`. Calls are paced `throttle` seconds apart regardless.
- Errors come back as `{"err": "<message>", "ECODE": "<code>"}`.
- A task id that names no task is answered **401** `Team not authorized`
  (`OAUTH_027`), not 404 (the adapter's first live read, 2026-11-23). On a
  task's path that code is therefore `NotFound`: a refused token fails
  every call, the board's own reads first.
- A list comes inside an envelope with one list in it (`tasks`, `lists`,
  `folders`, `tags`, `custom_items`). Only the task reads page: `page`
  counts from 0, and `last_page` says when to stop. `get_all` walks both.
- A repeated query key (`list_ids[]`, `tags[]`) is a list value here.

**One DELETE, and no other.** ClickUp takes a tag off a task with
`DELETE /task/{id}/tag/{name}`: the task stays, and so does the tag in the
Space. It is the only way to clear a label, so it is the only DELETE this
transport sends (Chris, 2026-11-23). Any other is refused here, before the
token is read or a byte goes out.

Errors never leave here as `urllib` exceptions; see `adapters.base`.
"""

from __future__ import annotations

import json
import re
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
    Unsupported,
    ValidationError,
)
from server.secrets import SecretUnavailable

API = "https://api.clickup.com/api/v2"
USER_AGENT = (
    "agentic-administration/0.0 (clickup adapter; "
    "+https://github.com/ChrisKornaros/agentic_administration)"
)
DEFAULT_THROTTLE = 0.7  # seconds between calls: under a Free workspace's 100 a minute
MAX_PAGES = 50  # a `get_all` stops here even if ClickUp never says `last_page`
NO_SUCH_TASK = "OAUTH_027"  # the ECODE of the 401 a missing task gets
SENT = ("GET", "POST", "PUT")  # the methods this transport sends, plus the one below
UNTAG = re.compile(r"^/task/[^/]+/tag/[^/]+$")  # a tag coming off a task: the one path a DELETE may name


def allowed(method: str, path: str) -> bool:
    """Whether this transport sends `method` to `path` at all."""
    return method in SENT or (method == "DELETE" and UNTAG.match(path) is not None)


class Transport(Protocol):
    """What the adapter needs; tests inject a fake with the same shape."""

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: Any = None) -> Any: ...

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> list[Any]: ...


def rows(body: Any) -> list[Any]:
    """The one list inside a ClickUp envelope; empty when there is none."""
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    lists = [v for v in body.values() if isinstance(v, list)]
    return lists[0] if len(lists) == 1 else []


class ClickUpTransport:
    def __init__(
        self,
        token: Callable[[], str],
        *,
        base_url: str = API,
        throttle: float = DEFAULT_THROTTLE,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._auth: str | None = None
        self.throttle = throttle
        self.timeout = timeout
        self._sleep, self._clock, self._open = sleep, clock, opener
        self._last: float | None = None
        # (method, path) of every request sent, in order: what the conformance
        # suite audits for "no delete, ever"
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
                self._auth = self._token()
            except SecretUnavailable as exc:
                raise AuthError(f"no ClickUp token: {exc}") from None
        return self._auth

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: Any = None) -> Any:
        if not allowed(method, path):
            raise Unsupported(f"the ClickUp transport sends no {method} to {path}: nothing is deleted, and the "
                              "only DELETE is a tag coming off a task")
        url = f"{self.base_url}{path}"
        if params:
            kept = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(kept, doseq=True)}"
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
            raise TransportError(f"could not reach ClickUp for {method} {path}: {exc.reason}") from None
        except TimeoutError:
            raise TransportError(f"timed out on {method} {path}") from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise TransportError(f"non-JSON answer to {method} {path}", detail=raw[:200]) from None

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        """Every row of a list read. A task read is walked page by page until
        `last_page`; any other envelope is one page."""
        params = dict(params or {})
        items: list[Any] = []
        for page in range(int(params.get("page") or 0), MAX_PAGES):
            body = self.request("GET", path, params=params)
            found = rows(body)
            items.extend(found)
            if not isinstance(body, dict) or "last_page" not in body or body["last_page"] or not found:
                break
            params["page"] = page + 1
        return items


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def _map_http_error(method: str, path: str, status: int, raw: str, headers: Mapping[str, str]) -> AdapterError:
    """Vendor failure → the project's taxonomy. ClickUp's error bodies hold a
    message and a code, never the Authorization header, so `detail` is safe."""
    where = f"{method} {path}"
    if 300 <= status < 400:
        return TransportError(f"HTTP {status} on {where}: redirected to {_header(headers, 'Location') or '(no Location)'}")
    message: str | None = None
    detail: str | None = None
    code: Any = None
    if raw and raw.lstrip()[:1] == "{":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            code = parsed.get("ECODE")
            message = " ".join(str(p) for p in (parsed.get("err"), f"({code})" if code else None) if p) or None
            detail = json.dumps(parsed)[:500]
    elif raw:
        detail = raw[:200]
    if status == 401 and code == NO_SUCH_TASK and path.startswith("/task/"):
        return NotFound(f"HTTP 401 on {where}: no such task, or one this token cannot reach ({message})", detail=detail)
    if status == 401:
        return AuthError(f"HTTP 401 on {where}: {message or 'the token was refused'}", detail=detail)
    if status == 403:
        return AuthError(f"HTTP 403 on {where}: {message or 'not permitted'}", detail=detail)
    if status == 404:
        return NotFound(f"HTTP 404 on {where}: {message or 'not found'}", detail=detail)
    if status == 429:
        reset = _header(headers, "X-RateLimit-Reset")
        return RateLimited(f"rate limited on {where}" + (f"; X-RateLimit-Reset is {reset}" if reset else ""), detail=detail)
    if 400 <= status < 500:
        return ValidationError(f"HTTP {status} on {where}: {message or 'rejected'}", detail=detail)
    return TransportError(f"HTTP {status} on {where}: {message or 'server error'}", detail=detail)
