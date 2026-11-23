"""The Teams bot in examples/teams/bot.py, against Microsoft's Teams SDK
itself: a fake Teams activity is posted to the app's own /api/messages
route, and everything the bot sends back is caught by a middleware on the
SDK's HTTP client, so nothing leaves the process. The SDK is the optional
`teams` group (`uv run --group teams pytest`); without it these skip."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("microsoft_teams.apps", reason="the Teams SDK is the optional `teams` dependency group")

import httpx2  # noqa: E402  (the Teams SDK's HTTP library, installed with it)
from microsoft_teams.apps import FastAPIAdapter  # noqa: E402
from microsoft_teams.common.http.client import Client  # noqa: E402

TEAMS = Path(__file__).resolve().parents[1] / "examples" / "teams"
_spec = importlib.util.spec_from_file_location("teams_bot", TEAMS / "bot.py")
bot = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bot
_spec.loader.exec_module(bot)
import bridge as bridge_module  # noqa: E402  (the module bot.py itself imported)

OWNER, STRANGER, TENANT = "aad-owner", "aad-stranger", "tenant-1"
SERVICE = "https://service.test"


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Service:
    """Stands in for Teams on the way out: records each call the bot makes and answers it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.refuse_edits = False

    def send(self, context, next):
        body = context.json if isinstance(context.json, dict) else {}
        self.calls.append((context.method, context.url.removeprefix(SERVICE), body))
        request = httpx2.Request(context.method, context.url)
        if self.refuse_edits and context.method == "PUT":
            return httpx2.Response(403, json={"error": {"code": "Forbidden"}}, request=request)
        return httpx2.Response(200, json={"id": f"sent-{len(self.calls)}"}, request=request)

    @property
    def texts(self) -> list[tuple[str, str]]:
        return [(method, body.get("text", "")) for method, _, body in self.calls]


class FakeAgent:
    def __init__(self) -> None:
        self.turns: list[str] = []
        self.gate: asyncio.Event | None = None

    async def run(self, session_id, resume, text, confirm):
        self.turns.append(text)
        if self.gate:
            await self.gate.wait()
        if text.startswith("write"):
            yield "Created AA-1." if await confirm("commit_item", {"token": "t-1"}) else "Nothing was written."
            return
        yield f"echo: {text}"
        if text == "two parts":
            yield "and a second part"


class Bot:
    def __init__(self, tmp_path, *, owner: str | None = OWNER, tenant: str | None = TENANT) -> None:
        self.service, self.agent, self.adapter = Service(), FakeAgent(), FastAPIAdapter()
        client = Client()
        client.use(self.service)
        self.bridge = owner and bridge_module.Bridge(self.agent, bridge_module.Sessions(tmp_path / "sessions.json"),
                                                     owner=owner, mode="metered")
        self.app, self.turns = bot.build(self.bridge or None, tenant=tenant, http_server_adapter=self.adapter,
                                         dangerously_allow_unauthenticated_requests=True, client=client)
        self._n = 0

    async def post(self, text: str, *, sender: str = OWNER, kind: str = "personal", tenant: str = TENANT,
                   activity_id: str | None = None) -> int:
        """Deliver one message as Teams would; the HTTP status the bot answered with."""
        if not getattr(self, "_ready", False):
            await self.app.initialize()
            self._ready = True
        self._n += 1
        body = json.dumps({
            "type": "message", "id": activity_id or f"act-{self._n}", "text": text, "channelId": "msteams",
            "serviceUrl": SERVICE + "/", "from": {"id": f"29:{sender}", "name": "A Person", "aadObjectId": sender},
            "recipient": {"id": "28:bot", "name": "Bot"},
            "conversation": {"id": "a:chat-1", "conversationType": kind, "tenantId": tenant},
            "channelData": {"tenant": {"id": tenant}}}).encode()
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                 "path": "/api/messages", "raw_path": b"/api/messages", "query_string": b"", "root_path": "",
                 "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                 "client": ("127.0.0.1", 1), "server": ("test", 80), "scheme": "http"}
        sent: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            sent.append(message)

        await self.adapter.app(scope, receive, send)
        return next(m["status"] for m in sent if m["type"] == "http.response.start")

    async def settle(self) -> None:
        """Let the running turns end, or reach a write that waits for its yes."""
        for _ in range(400):
            await asyncio.sleep(0.005)
            if not self.turns or (self.bridge and self.bridge.waiting(f"{TENANT}:a:chat-1")):
                return
        raise AssertionError("the turn neither ended nor asked")


@pytest.mark.anyio
async def test_a_direct_message_is_answered_in_place_of_the_working_message(tmp_path):
    b = Bot(tmp_path)
    assert await b.post("hello") == 200
    await b.settle()
    (m1, path1, first), (m2, path2, second) = b.service.calls
    assert (m1, path1, first["text"]) == ("POST", "/v3/conversations/a:chat-1/activities", bot.WORKING)
    assert (m2, path2) == ("PUT", "/v3/conversations/a:chat-1/activities/sent-1")  # the placeholder, edited
    assert (second["text"], second["textFormat"]) == ("echo: hello", "extendedmarkdown")
    assert b.agent.turns == ["hello"]


@pytest.mark.anyio
async def test_teams_gets_its_answer_before_the_turn_is_over(tmp_path):
    b = Bot(tmp_path)
    b.agent.gate = asyncio.Event()
    assert await b.post("hello") == 200  # the handler returned; Teams' 25 seconds are not spent on the agent
    await asyncio.sleep(0.02)
    assert b.service.texts == [("POST", bot.WORKING)] and len(b.turns) == 1
    b.agent.gate.set()
    await b.settle()
    assert b.service.texts[-1] == ("PUT", "echo: hello")


@pytest.mark.anyio
async def test_only_the_first_part_of_an_answer_replaces_the_working_message(tmp_path):
    b = Bot(tmp_path)
    await b.post("two parts")
    await b.settle()
    assert b.service.texts == [("POST", bot.WORKING), ("PUT", "echo: two parts"), ("POST", "and a second part")]


@pytest.mark.anyio
async def test_a_write_waits_for_a_yes_typed_as_the_next_message(tmp_path):
    b = Bot(tmp_path)
    await b.post("write it")
    await b.settle()
    assert b.service.texts[0] == ("POST", bot.WORKING) and "**commit_item**" in b.service.texts[1][1]
    await b.post("yes")
    await b.settle()
    assert b.service.texts[2:] == [("POST", "Created AA-1.")]  # the yes started no turn and got no working message
    assert b.agent.turns == ["write it"]


@pytest.mark.anyio
async def test_a_message_teams_delivers_twice_runs_once(tmp_path):
    b = Bot(tmp_path)
    await b.post("hello", activity_id="act-same")
    await b.post("hello", activity_id="act-same")
    await b.settle()
    assert b.agent.turns == ["hello"] and [t for _, t in b.service.texts].count(bot.WORKING) == 1


@pytest.mark.anyio
async def test_an_edit_teams_refuses_still_delivers_the_answer(tmp_path):
    b = Bot(tmp_path)
    b.service.refuse_edits = True
    await b.post("hello")
    await b.settle()
    assert b.service.texts == [("POST", bot.WORKING), ("PUT", "echo: hello"), ("POST", "echo: hello")]


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["channel", "groupChat"])
async def test_outside_a_direct_chat_it_says_so_and_runs_nothing(tmp_path, kind):
    b = Bot(tmp_path)
    await b.post("hello", kind=kind)
    await b.settle()
    assert b.service.texts == [("POST", bot.DIRECT_ONLY)] and b.agent.turns == []


@pytest.mark.anyio
async def test_a_message_from_another_tenant_is_dropped_in_silence(tmp_path):
    b = Bot(tmp_path)
    assert await b.post("hello", tenant="tenant-2") == 200
    await b.settle()
    assert b.service.calls == [] and b.agent.turns == []


@pytest.mark.anyio
async def test_someone_not_on_the_list_is_refused_by_the_bridge(tmp_path):
    b = Bot(tmp_path)
    await b.post("hello", sender=STRANGER)
    await b.settle()
    assert b.service.texts == [("POST", bridge_module.REFUSED)] and b.agent.turns == []


@pytest.mark.anyio
async def test_with_no_owner_set_nobody_is_served_and_each_sender_learns_their_id(tmp_path):
    b = Bot(tmp_path, owner=None)
    await b.post("hello", sender=STRANGER)
    assert b.service.texts == [("POST", bot.NO_OWNER.format(sender=STRANGER))] and STRANGER in b.service.texts[0][1]


def test_a_long_answer_is_cut_into_messages_at_blank_lines():
    text = "\n\n".join("p" * 5000 for _ in range(5))
    parts = bot.pieces(text)
    assert len(parts) == 3 and all(len(p) <= bot.PIECE for p in parts) and "".join(parts).count("p") == 25000
    assert bot.pieces("short") == ["short"] and bot.pieces("") == [] and len(bot.pieces("x" * 30000)) == 3
