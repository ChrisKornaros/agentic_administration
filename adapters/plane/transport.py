"""HTTP transport for Plane Cloud — the only file that knows the wire.

Carried over from the seed CLI's live findings (tools/plane/API.md):

- Cloudflare fronts `api.plane.so` and 1010-bans the default `Python-urllib`
  User-Agent, so every request sends the explicit `USER_AGENT`.
- Auth is the `X-API-Key` header. The token is fetched lazily from the
  secrets boundary on the first request, never at construction.
- The API rate-limits at ~40–60 req/min (429) and puts a managed challenge
  in front of sustained POST volume (a 403 HTML page). Calls are paced
  `throttle` seconds apart; the walls map to `RateLimited` / `Blocked`.
- List endpoints answer with a bare list or a cursor envelope
  (`results`, `next_cursor`, `next_page_results`); `get_all` walks both.

Errors never leave here as `urllib` exceptions — see `adapters.base`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Protocol

from adapters.base import (
    AdapterError,
    AuthError,
    Blocked,
    NotFound,
    RateLimited,
    TransportError,
    ValidationError,
)
from server.secrets import SecretUnavailable

DEFAULT_BASE_URL = "https://api.plane.so/api/v1"
USER_AGENT = (
    "agentic-administration/0.0 (plane adapter; "
    "+https://github.com/ChrisKornaros/agentic_administration)"
)
DEFAULT_THROTTLE = 1.5  # seconds between calls; the Phase 1 probe's pace


class Transport(Protocol):
    """What the adapter needs; tests inject a fake with the same shape."""

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: Any = None) -> Any: ...

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> list[Any]: ...


class PlaneTransport:
    def __init__(
        self,
        token: Callable[[], str],
        *,
        base_url: str | None = None,
        throttle: float = DEFAULT_THROTTLE,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._token = token
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.throttle = throttle
        self.timeout = timeout
        self._sleep, self._clock, self._open = sleep, clock, opener
        self._last: float | None = None
        self.calls = 0

    # -- pacing ----------------------------------------------------------------

    def _pace(self) -> None:
        now = self._clock()
        if self._last is not None:
            wait = self.throttle - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last = now

    # -- one request -----------------------------------------------------------

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: Any = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
        try:
            token = self._token()
        except SecretUnavailable as exc:
            raise AuthError(f"no API token: {exc}") from None
        headers = {
            "X-API-Key": token,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, method=method, headers=headers, data=data)
        self._pace()
        self.calls += 1
        try:
            with self._open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise _map_http_error(method, path, exc.code, exc.read().decode("utf-8", "replace")) from None
        except urllib.error.URLError as exc:
            raise TransportError(f"could not reach Plane for {method} {path}: {exc.reason}") from None
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
        params.setdefault("per_page", 100)
        items: list[Any] = []
        seen: set[str] = set()
        while True:
            page = self.request("GET", path, params=params)
            if isinstance(page, list):
                return items + page
            if not isinstance(page, dict):
                return items
            items.extend(page.get("results") or [])
            cursor = page.get("next_cursor")
            if not (page.get("next_page_results") and cursor) or cursor in seen:
                return items
            seen.add(cursor)
            params["cursor"] = cursor


def _map_http_error(method: str, path: str, status: int, raw: str) -> AdapterError:
    """Vendor failure → the project's taxonomy. The token never appears in
    `raw` (Plane echoes request bodies at most), so `detail` is safe."""
    where = f"{method} {path}"
    looks_html = raw.lstrip()[:1] == "<"
    detail: str | None = None
    message = None
    if not looks_html and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            message = parsed.get("detail") or parsed.get("error") or parsed.get("error_message") or parsed.get("message")
            if message is None:
                # DRF field errors: {"name": ["This field is required."]}
                message = "; ".join(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in parsed.items())
            detail = json.dumps(parsed)[:500]
        elif parsed is not None:
            message = str(parsed)[:200]
            detail = raw[:500]
    if looks_html:
        return Blocked(f"HTTP {status} on {where} answered by an edge wall (Cloudflare), not Plane", detail=raw[:200])
    if status == 429:
        return RateLimited(f"rate limited on {where}: {message or 'RATE_LIMIT_EXCEEDED'}", detail=detail)
    if status in (401, 403):
        return AuthError(f"HTTP {status} on {where}: {message or 'not authorized'}", detail=detail)
    if status == 404:
        return NotFound(f"HTTP 404 on {where}: {message or 'not found'}", detail=detail)
    if 400 <= status < 500:
        return ValidationError(f"HTTP {status} on {where}: {message or 'rejected'}", detail=detail)
    return TransportError(f"HTTP {status} on {where}: {message or 'server error'}", detail=detail)
