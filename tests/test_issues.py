"""The open-issues read: the config, `GitHubIssues` against the fake endpoint,
`OpenIssues` and the `issues` MCP server, all offline. The stdio entry point
is tested through the plugin's own command, in tests/test_examples.py."""

import re
from pathlib import Path

import pytest
from mcp import Client

from adapters.base import AuthError, NotFound, RateLimited, TransportError
from issues import github
from issues.config import GITHUB_API, InvalidIssuesConfig, IssuesConfig, from_dict, load
from issues.github import GitHubIssues
from issues.mcp_app import build
from issues.reader import MAX_LIMIT, IssuesFailure, OpenIssues
from server.secrets import SecretUnavailable
from tests.fake_github import API, REPOSITORY, TOKEN, FakeGitHub, record

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "issues" / "github.example.toml"
ISSUE_TOOLS = {"find_open_issues"}
PATTERN = r"^Board: (\S+)\s*$"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def source(fake: FakeGitHub) -> GitHubIssues:
    return GitHubIssues(API, REPOSITORY, lambda: TOKEN, opener=fake)


def reader(fake: FakeGitHub, pattern: str | None = PATTERN) -> OpenIssues:
    return OpenIssues(IssuesConfig("ISSUES_TOKEN", "github", REPOSITORY, API, pattern), source(fake))


# -- the config ----------------------------------------------------------------------------


def test_the_example_config_loads():
    cfg = load(EXAMPLE)
    assert (cfg.kind, cfg.repository, cfg.api, cfg.token_env) == ("github", "example-org/example-repo", GITHUB_API, "ISSUES_TOKEN")
    assert re.compile(cfg.key_pattern, re.M).search("text\nBoard: AA-12\n").group(1) == "AA-12"


def test_the_board_server_skips_the_example_as_it_has_no_backend(tmp_path):
    from server.config import load_boards

    (tmp_path / "issues.toml").write_text(EXAMPLE.read_text())
    (tmp_path / "board.toml").write_text((ROOT / "examples" / "boards" / "plane.example.toml").read_text())
    boards, skipped = load_boards([str(tmp_path)])
    assert list(boards) == ["board"] and [p.name for p in skipped] == ["issues.toml"]


@pytest.mark.parametrize("change, problem", [
    ({"connection": {"token_env": "ISSUES_TOKEN", "token": "abc"}}, "secrets never go in this file"),
    ({"connection": {"token_env": "not a name"}}, "the *name* of an environment variable"),
    ({"source": {"kind": "other", "repository": REPOSITORY}}, "source.kind must be one of"),
    ({"source": {"kind": "github", "repository": "no-slash"}}, "owner/name"),
    ({"source": {"kind": "github", "repository": REPOSITORY, "api": "http://plain.test"}}, "https://"),
    ({"match": {"key_pattern": "no group"}}, "exactly one group"),
    ({"match": {"key_pattern": "(unclosed"}}, "not a regular expression"),
    ({"extra": {}}, "unknown top-level keys: extra"),
    ({"source": {"kind": "github"}}, "source needs: repository"),
])
def test_a_bad_config_names_every_problem(change, problem):
    data = {"connection": {"token_env": "ISSUES_TOKEN"}, "source": {"kind": "github", "repository": REPOSITORY}} | change
    with pytest.raises(InvalidIssuesConfig) as exc:
        from_dict(data)
    assert any(problem in p for p in exc.value.problems)


# -- the wire ------------------------------------------------------------------------------


def test_open_issues_come_newest_first_without_pull_requests_or_closed_ones():
    fake = FakeGitHub([
        record(1, "Old", updated="2026-01-01T00:00:00Z"),
        record(2, "A pull request", pull_request=True, updated="2026-03-01T00:00:00Z"),
        record(3, "New", labels=("bug", "ui"), body="Details", updated="2026-02-01T10:00:00Z"),
        record(4, "Closed", state="closed"),
    ])
    found = source(fake).open_issues(50)
    assert [(i.number, i.title, i.updated) for i in found] == [(3, "New", "2026-02-01"), (1, "Old", "2026-01-01")]
    assert found[0].labels == ("bug", "ui") and found[0].body == "Details"
    assert found[0].url == f"https://github.test/{REPOSITORY}/issues/3"


def test_a_null_body_reads_as_empty():
    assert source(FakeGitHub([record(1, "No body", body=None)])).open_issues(5)[0].body == ""


def test_every_request_is_a_get_with_the_token_and_the_pinned_api_version():
    fake = FakeGitHub([record(n, f"Issue {n}") for n in range(1, 6)], page_size=2)
    src = source(fake)
    assert len(src.open_issues(50)) == 5 and len(fake.requests) == 3  # the Link header is followed to the end
    for req in fake.requests:
        assert req.get_method() == "GET"
        assert req.get_header("Authorization") == f"Bearer {TOKEN}"
        assert req.get_header("X-github-api-version") == github.API_VERSION
    assert {method for method, _ in src.log} == {"GET"}


def test_the_read_stops_at_the_limit():
    fake = FakeGitHub([record(n, f"Issue {n}") for n in range(1, 8)], page_size=2)
    assert len(source(fake).open_issues(3)) == 3 and len(fake.requests) == 2


def test_a_next_page_on_another_host_is_refused_so_the_token_stays_home():
    fake = FakeGitHub([record(n, f"Issue {n}") for n in range(1, 4)], page_size=2)
    fake.next_host = "https://elsewhere.test"
    with pytest.raises(TransportError, match="another host"):
        source(fake).open_issues(50)
    assert len(fake.requests) == 1


@pytest.mark.parametrize("status, headers, kind", [
    (401, {}, AuthError),
    (403, {}, AuthError),
    (403, {"X-RateLimit-Remaining": "0"}, RateLimited),
    (403, {"Retry-After": "60"}, RateLimited),
    (429, {}, RateLimited),
    (404, {}, NotFound),
    (500, {}, TransportError),
])
def test_a_failure_maps_to_the_projects_errors(status, headers, kind):
    fake = FakeGitHub()
    fake.fail = (status, headers, '{"message": "Bad credentials"}')
    with pytest.raises(kind) as exc:
        source(fake).open_issues(5)
    assert TOKEN not in str(exc.value)


def test_a_missing_token_is_an_auth_error_and_sends_nothing():
    def no_token() -> str:
        raise SecretUnavailable("ISSUES_TOKEN is not set")

    fake = FakeGitHub([record(1, "One")])
    with pytest.raises(AuthError, match="ISSUES_TOKEN"):
        GitHubIssues(API, REPOSITORY, no_token, opener=fake).open_issues(5)
    assert fake.requests == []


def test_the_wire_file_sends_nothing_but_get():
    text = (ROOT / "issues" / "github.py").read_text()
    assert set(re.findall(r'method="([A-Z]+)"', text)) == {"GET"}


# -- the read ------------------------------------------------------------------------------


def test_each_issue_names_the_board_keys_in_its_text_and_carries_no_body():
    fake = FakeGitHub([
        record(1, "Filed from the board", body="Do the thing.\n\nBoard: AA-12\n", updated="2026-02-02T00:00:00Z"),
        record(2, "Filed by hand", body="Mentions Board: AA-99 mid-line only.", updated="2026-02-01T00:00:00Z"),
        record(3, "Two keys", body="Board: AA-1\nBoard: AA-2\nBoard: AA-1", updated="2026-01-01T00:00:00Z"),
    ])
    found = reader(fake).find_open_issues()
    assert found[0] == {"number": 1, "title": "Filed from the board", "url": f"https://github.test/{REPOSITORY}/issues/1",
                        "labels": [], "updated": "2026-02-02", "item_keys": ["AA-12"]}
    assert [i["item_keys"] for i in found] == [["AA-12"], [], ["AA-1", "AA-2"]]


def test_with_no_pattern_no_issue_names_a_key():
    fake = FakeGitHub([record(1, "One", body="Board: AA-12")])
    assert reader(fake, pattern=None).find_open_issues()[0]["item_keys"] == []


def test_the_limit_is_kept_between_one_and_the_maximum():
    fake = FakeGitHub([record(n, f"Issue {n}") for n in range(1, MAX_LIMIT + 50)])
    r = reader(fake)
    assert len(r.find_open_issues(0)) == 1 and len(r.find_open_issues(10_000)) == MAX_LIMIT


@pytest.mark.parametrize("status, headers, words", [
    (401, {}, "The operator must fix the token"),
    (404, {}, "The operator must fix the repository or the token's access"),
    (429, {}, "Wait a few minutes"),
    (500, {}, "Retry shortly"),
])
def test_a_failure_tells_the_agent_what_to_do(status, headers, words):
    fake = FakeGitHub()
    fake.fail = (status, headers, "{}")
    with pytest.raises(IssuesFailure, match=words):
        reader(fake).find_open_issues()


# -- the server ----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_server_has_one_read_only_tool():
    async with Client(build(reader(FakeGitHub([record(1, "One", body="Board: AA-12")])))) as client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == ISSUE_TOOLS and all(t.annotations.read_only_hint for t in tools)
        result = await client.call_tool("find_open_issues", {"limit": 5})
    assert result.structured_content["issues"][0]["item_keys"] == ["AA-12"]


@pytest.mark.anyio
async def test_a_failure_reaches_the_client_as_a_tool_error():
    fake = FakeGitHub()
    fake.fail = (401, {}, "{}")
    async with Client(build(reader(fake))) as client:
        result = await client.call_tool("find_open_issues", {})
    assert result.is_error and "The operator must fix the token" in result.content[0].text


@pytest.mark.anyio
async def test_with_nothing_configured_the_server_has_no_tools():
    async with Client(build(None)) as client:
        assert (await client.list_tools()).tools == []
