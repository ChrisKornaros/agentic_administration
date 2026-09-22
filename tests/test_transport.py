"""The Plane transport: headers, pacing, pagination and error mapping —
with an injected opener, never the network."""

import io
import json
import urllib.error

import pytest

from adapters.base import (
    AuthError,
    Blocked,
    NotFound,
    RateLimited,
    TransportError,
    ValidationError,
)
from adapters.plane.transport import USER_AGENT, PlaneTransport


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_for(answers):
    """answers: list of bytes | HTTPError | URLError, consumed in order; records requests."""
    seen = []

    def open_(req, timeout):
        seen.append(req)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Response(answer)

    open_.seen = seen
    return open_


def http_error(code, body: str):
    return urllib.error.HTTPError("https://x", code, "msg", {}, io.BytesIO(body.encode()))


def make(answers, **kw):
    ticks = iter(range(0, 1000))
    slept = []
    t = PlaneTransport(lambda: "tok", opener=opener_for(answers), sleep=slept.append,
                       clock=lambda: float(next(ticks)) * 0.5, **kw)
    t.slept = slept
    return t


def test_headers_body_and_lazy_token():
    calls = []
    t = PlaneTransport(lambda: calls.append(1) or "tok", opener=opener_for([b'{"ok": true}']), sleep=lambda s: None)
    assert calls == []  # nothing resolved at construction
    assert t.request("POST", "/p", params={"a": 1, "b": None}, body={"name": "x"}) == {"ok": True}
    req = t._open.seen[0]
    assert req.full_url == "https://api.plane.so/api/v1/p?a=1"
    assert req.get_header("X-api-key") == "tok" and req.get_header("User-agent") == USER_AGENT
    assert req.get_header("Content-type") == "application/json" and json.loads(req.data) == {"name": "x"}
    assert calls == [1]


def test_pacing_waits_between_calls():
    t = make([b"[]", b"[]", b"[]"], throttle=1.5)
    for _ in range(3):
        t.request("GET", "/x")
    assert t.slept and all(0 < s <= 1.5 for s in t.slept)


def test_get_all_walks_the_cursor_and_accepts_bare_lists():
    t = make([
        json.dumps({"results": [1, 2], "next_cursor": "c2", "next_page_results": True}).encode(),
        json.dumps({"results": [3], "next_cursor": "", "next_page_results": False}).encode(),
        b"[4, 5]",
    ], throttle=0)
    assert t.get_all("/items") == [1, 2, 3]
    assert "cursor=c2" in t._open.seen[1].full_url
    assert t.get_all("/bare") == [4, 5]


@pytest.mark.parametrize(
    "code, body, kind, fragment",
    [
        (403, '{"detail": "Given API token is not valid"}', AuthError, "token is not valid"),
        (401, "", AuthError, "not authorized"),
        (404, '{"detail": "Not found."}', NotFound, "Not found"),
        (400, '{"name": ["This field is required."]}', ValidationError, "name: This field is required."),
        (400, '{"error": "Cycles are not enabled for this project"}', ValidationError, "Cycles are not enabled"),
        (429, '{"error_code": 5900, "error_message": "RATE_LIMIT_EXCEEDED"}', RateLimited, "RATE_LIMIT_EXCEEDED"),
        (403, "<!DOCTYPE html><html>Attention Required! | Cloudflare</html>", Blocked, "edge wall"),
        (502, "<html>bad gateway</html>", Blocked, "edge wall"),
        (500, '{"detail": "boom"}', TransportError, "boom"),
    ],
)
def test_http_errors_map_to_the_taxonomy(code, body, kind, fragment):
    t = make([http_error(code, body)], throttle=0)
    with pytest.raises(kind, match=fragment):
        t.request("GET", "/x")


def test_network_failure_and_non_json():
    t = make([urllib.error.URLError("dns down")], throttle=0)
    with pytest.raises(TransportError, match="dns down"):
        t.request("GET", "/x")
    t = make([b"<html>weird</html>"], throttle=0)
    with pytest.raises(TransportError, match="non-JSON"):
        t.request("GET", "/x")
    assert make([b""], throttle=0).request("GET", "/x") is None
