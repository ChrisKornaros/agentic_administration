"""The Jira transport: Basic auth, pacing, pagination and error mapping —
with an injected opener, never the network."""

import base64
import io
import json
import urllib.error

import pytest

from adapters.base import AuthError, NotFound, RateLimited, TransportError, ValidationError
from adapters.jira.transport import USER_AGENT, JiraTransport, site_url
from tests.test_transport import opener_for


def http_error(code, body: str, headers=None):
    return urllib.error.HTTPError("https://x", code, "msg", headers or {}, io.BytesIO(body.encode()))


def make(answers, **kw):
    ticks = iter(range(0, 1000))
    slept = []
    t = JiraTransport("example.atlassian.net", lambda: "me@example.invalid", lambda: "tok",
                      opener=opener_for(answers), sleep=slept.append, clock=lambda: float(next(ticks)) * 0.25, **kw)
    t.slept = slept
    return t


def test_site_url():
    assert site_url("example.atlassian.net") == "https://example.atlassian.net"
    assert site_url("https://example.atlassian.net/") == "https://example.atlassian.net"


def test_basic_auth_is_lazy_and_resolved_once():
    asked = []
    t = JiraTransport("example.atlassian.net", lambda: asked.append("user") or "me@example.invalid",
                      lambda: asked.append("token") or "tok", opener=opener_for([b'{"ok": 1}', b""]), sleep=lambda s: None)
    assert asked == []
    assert t.request("POST", "/rest/api/3/issue", params={"a": 1, "b": None}, body={"fields": {}}) == {"ok": 1}
    assert t.request("GET", "/x") is None
    req = t._open.seen[0]
    assert req.full_url == "https://example.atlassian.net/rest/api/3/issue?a=1"
    assert req.get_header("Authorization") == "Basic " + base64.b64encode(b"me@example.invalid:tok").decode()
    assert req.get_header("User-agent") == USER_AGENT and json.loads(req.data) == {"fields": {}}
    assert asked == ["user", "token"]  # once, not per request
    assert t.log == [("POST", "/rest/api/3/issue"), ("GET", "/x")]


def test_pacing_waits_between_calls():
    t = make([b"[]", b"[]", b"[]"], throttle=0.5)
    for _ in range(3):
        t.request("GET", "/x")
    assert t.slept and all(0 < s <= 0.5 for s in t.slept)


def test_get_all_walks_start_at_pages_and_accepts_bare_lists():
    t = make([
        json.dumps({"startAt": 0, "maxResults": 2, "total": 3, "isLast": False, "values": ["a", "b"]}).encode(),
        json.dumps({"startAt": 2, "maxResults": 2, "total": 3, "isLast": True, "values": ["c"]}).encode(),
        b'[{"id": 1}]',
    ], throttle=0)
    assert t.get_all("/rest/api/3/label") == ["a", "b", "c"]
    assert "startAt=2" in t._open.seen[1].full_url
    assert t.get_all("/rest/api/3/user/assignable/search") == [{"id": 1}]


@pytest.mark.parametrize(
    "code, body, headers, kind, fragment",
    [
        (401, "", {}, AuthError, "not retried"),
        (401, "", {"X-Seraph-LoginReason": "AUTHENTICATION_DENIED"}, AuthError, "CAPTCHA"),
        (403, '{"errorMessages": ["You do not have permission"], "errors": {}}', {}, AuthError, "permission"),
        (404, '{"errorMessages": ["Issue does not exist"], "errors": {}}', {}, NotFound, "does not exist"),
        (400, '{"errorMessages": [], "errors": {"labels": "contains spaces"}}', {}, ValidationError, "labels: contains spaces"),
        (429, "", {"Retry-After": "7"}, RateLimited, "retry after 7s"),
        (410, '{"errorMessages": ["The requested API has been removed."]}', {}, TransportError, "removed"),
        (503, "<html>unavailable</html>", {}, TransportError, "server error"),
    ],
)
def test_http_errors_map_to_the_taxonomy(code, body, headers, kind, fragment):
    t = make([http_error(code, body, headers)], throttle=0)
    with pytest.raises(kind, match=fragment):
        t.request("GET", "/x")


def test_a_401_is_sent_once():
    t = make([http_error(401, "")], throttle=0)
    with pytest.raises(AuthError):
        t.request("GET", "/x")
    assert len(t._open.seen) == 1


def test_network_failure_and_non_json():
    t = make([urllib.error.URLError("dns down")], throttle=0)
    with pytest.raises(TransportError, match="dns down"):
        t.request("GET", "/x")
    t = make([b"<html>weird</html>"], throttle=0)
    with pytest.raises(TransportError, match="non-JSON"):
        t.request("GET", "/x")
