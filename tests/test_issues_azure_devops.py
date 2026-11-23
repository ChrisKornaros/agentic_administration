"""The Azure DevOps source: the config's second kind, the wire, and the same
read and server the GitHub source goes through."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from mcp import Client

from adapters.base import AuthError, NotFound, RateLimited, TransportError
from issues import azure_devops
from issues.__main__ import make_source
from issues.azure_devops import AzureDevOpsPullRequests
from issues.config import AZURE_DEVOPS_API, InvalidIssuesConfig, IssuesConfig, from_dict, load
from issues.mcp_app import build
from issues.reader import IssuesFailure, OpenIssues
from server.secrets import SecretUnavailable
from tests.fake_azure_devops import API, ORGANIZATION, PROJECT, REPOSITORY, TOKEN, FakeAzureDevOps, record

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "issues" / "azure-devops.example.toml"
PATTERN = r"^\[([A-Za-z][A-Za-z0-9]*-\d+)\]"
WEB = f"{API}/{ORGANIZATION}/Example%20Project/_git"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def source(fake: FakeAzureDevOps, repository: str = REPOSITORY, auth: str = "pat") -> AzureDevOpsPullRequests:
    return AzureDevOpsPullRequests(API, ORGANIZATION, repository, lambda: TOKEN, auth=auth, opener=fake)


def reader(fake: FakeAzureDevOps, pattern: str | None = PATTERN) -> OpenIssues:
    cfg = IssuesConfig("ISSUES_TOKEN", "azure_devops", REPOSITORY, API, pattern, ORGANIZATION, "pat")
    return OpenIssues(cfg, source(fake))


# -- the config ----------------------------------------------------------------------------


def test_the_example_config_loads_and_makes_this_source():
    cfg = load(EXAMPLE)
    assert (cfg.kind, cfg.organization, cfg.repository, cfg.api, cfg.auth, cfg.token_env) == (
        "azure_devops", "example-org", "Example Project/example-repo", AZURE_DEVOPS_API, "pat", "ISSUES_TOKEN")
    assert re.compile(cfg.key_pattern, re.M).search("[AA-12] Fix the export\nfeature/x\n").group(1) == "AA-12"
    assert isinstance(make_source(cfg), AzureDevOpsPullRequests)


def test_auth_defaults_to_a_personal_access_token_and_a_whole_project_is_a_star():
    cfg = from_dict({"connection": {"token_env": "T"},
                     "source": {"kind": "azure_devops", "organization": "example-org", "repository": "Example Project/*"}})
    assert (cfg.auth, cfg.repository) == ("pat", "Example Project/*")


@pytest.mark.parametrize("change, problem", [
    ({"source": {"kind": "azure_devops", "repository": REPOSITORY}}, "source needs: organization"),
    ({"source": {"kind": "azure_devops", "organization": "https://dev.azure.com/x", "repository": REPOSITORY}}, "not a URL"),
    ({"source": {"kind": "azure_devops", "organization": ORGANIZATION, "repository": "no-slash"}}, "Project/repository"),
    ({"source": {"kind": "azure_devops", "organization": ORGANIZATION, "repository": "a/b/c"}}, "Project/repository"),
    ({"connection": {"token_env": "T", "auth": "basic"}}, "connection.auth must be one of"),
    ({"connection": {"token_env": "T", "token": "abc"}}, "secrets never go in this file"),
])
def test_a_bad_config_names_the_problem(change, problem):
    data = {"connection": {"token_env": "T"},
            "source": {"kind": "azure_devops", "organization": ORGANIZATION, "repository": REPOSITORY}} | change
    with pytest.raises(InvalidIssuesConfig) as exc:
        from_dict(data)
    assert any(problem in p for p in exc.value.problems)


@pytest.mark.parametrize("change, problem", [
    ({"source": {"kind": "github", "repository": "example-org/example-repo", "organization": "x"}}, "source.organization is for kind azure_devops only"),
    ({"connection": {"token_env": "T", "auth": "pat"}}, "connection.auth is for kind azure_devops only"),
])
def test_the_other_kind_refuses_this_kinds_keys(change, problem):
    data = {"connection": {"token_env": "T"}, "source": {"kind": "github", "repository": "example-org/example-repo"}} | change
    with pytest.raises(InvalidIssuesConfig) as exc:
        from_dict(data)
    assert problem in exc.value.problems


# -- the wire ------------------------------------------------------------------------------


def test_active_pull_requests_come_newest_first_as_issues():
    fake = FakeAzureDevOps([
        record(1, "Old", created="2026-01-01T00:00:00Z"),
        record(2, "Merged", status="completed", created="2026-03-01T00:00:00Z"),
        record(3, "[AA-7] New", description="Details", branch="feature/AA-7-new", labels=("bug",), inactive_labels=("gone",),
               created="2026-02-01T10:00:00Z"),
        record(4, "Another repository's", repo="other-repo", created="2026-04-01T00:00:00Z"),
    ])
    found = source(fake).open_issues(50)
    assert [(i.number, i.title, i.updated) for i in found] == [(3, "[AA-7] New", "2026-02-01"), (1, "Old", "2026-01-01")]
    assert found[0].labels == ("bug",) and found[0].url == f"{WEB}/example-repo/pullrequest/3"
    assert found[0].body == "[AA-7] New\nfeature/AA-7-new\nDetails"  # where a key is looked for, a line each


def test_a_star_reads_the_whole_project_and_links_each_to_its_own_repository():
    fake = FakeAzureDevOps([record(1, "Here"), record(4, "There", repo="other-repo", created="2026-04-01T00:00:00Z")])
    found = source(fake, f"{PROJECT}/*").open_issues(50)
    assert [i.url for i in found] == [f"{WEB}/other-repo/pullrequest/4", f"{WEB}/example-repo/pullrequest/1"]
    assert "/_apis/git/pullrequests?" in fake.requests[0].full_url


def test_a_pull_request_with_no_description_still_reads():
    assert source(FakeAzureDevOps([record(1, "Bare", description=None)])).open_issues(5)[0].body == "Bare\nfeature/x\n"


def test_every_request_is_a_get_that_asks_for_no_sign_in_redirect():
    fake = FakeAzureDevOps([record(n, f"PR {n}") for n in range(1, 6)], page_size=2)
    src = source(fake)
    assert len(src.open_issues(50)) == 5 and len(fake.requests) == 4  # 2, 2, 1, then the empty page that ends it
    basic = "Basic " + base64.b64encode(f":{TOKEN}".encode()).decode()
    for req in fake.requests:
        assert req.get_method() == "GET" and req.get_header("Authorization") == basic
        assert req.get_header("X-tfs-fedauthredirect") == "Suppress"
        assert f"api-version={azure_devops.API_VERSION}" in req.full_url
    assert {method for method, _ in src.log} == {"GET"}


def test_an_entra_token_goes_as_a_bearer_token():
    fake = FakeAzureDevOps([record(1, "One")])
    source(fake, auth="bearer").open_issues(5)
    assert fake.requests[0].get_header("Authorization") == f"Bearer {TOKEN}"


def test_the_read_stops_at_the_limit():
    fake = FakeAzureDevOps([record(n, f"PR {n}") for n in range(1, 8)], page_size=2)
    assert len(source(fake).open_issues(3)) == 3 and len(fake.requests) == 2


def test_the_default_opener_follows_no_redirect_so_the_token_stays_home():
    assert azure_devops._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://elsewhere.test") is None


@pytest.mark.parametrize("status, kind", [
    (401, AuthError), (403, AuthError), (302, AuthError), (404, NotFound), (429, RateLimited), (500, TransportError)])
def test_a_failure_maps_to_the_projects_errors(status, kind):
    fake = FakeAzureDevOps()
    fake.fail = (status, '{"message": "TF400813: not authorized"}')
    with pytest.raises(kind) as exc:
        source(fake).open_issues(5)
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize("answer", [(203, "<html>Sign in</html>"), (200, "<!DOCTYPE html><html>Sign in</html>")])
def test_a_sign_in_page_is_an_auth_error_whatever_its_status(answer):
    fake = FakeAzureDevOps()
    fake.answer = answer
    with pytest.raises(AuthError, match="does not accept the token"):
        source(fake).open_issues(5)


def test_an_answer_that_is_not_a_list_of_pull_requests_is_a_transport_error():
    fake = FakeAzureDevOps()
    fake.answer = (200, '{"count": 0}')
    with pytest.raises(TransportError, match="not a list of pull requests"):
        source(fake).open_issues(5)


def test_a_missing_token_is_an_auth_error_and_sends_nothing():
    def no_token() -> str:
        raise SecretUnavailable("ISSUES_TOKEN is not set")

    fake = FakeAzureDevOps([record(1, "One")])
    with pytest.raises(AuthError, match="ISSUES_TOKEN"):
        AzureDevOpsPullRequests(API, ORGANIZATION, REPOSITORY, no_token, opener=fake).open_issues(5)
    assert fake.requests == []


def test_the_wire_file_sends_nothing_but_get():
    text = (ROOT / "issues" / "azure_devops.py").read_text()
    assert set(re.findall(r'method="([A-Z]+)"', text)) == {"GET"}


# -- the read and the server -----------------------------------------------------------------


def test_a_key_is_read_from_the_title_the_branch_or_the_description():
    fake = FakeAzureDevOps([
        record(3, "[AA-12] In the title", created="2026-03-01T00:00:00Z"),
        record(2, "In the branch", branch="[AA-13]-fix", created="2026-02-01T00:00:00Z"),
        record(1, "In the description", description="Why.\n[AA-14] is the item.", created="2026-01-01T00:00:00Z"),
        record(0, "Names none", created="2025-12-01T00:00:00Z"),
    ])
    found = reader(fake).find_open_issues()
    assert [i["item_keys"] for i in found] == [["AA-12"], ["AA-13"], ["AA-14"], []]
    assert found[0] == {"number": 3, "title": "[AA-12] In the title", "url": f"{WEB}/example-repo/pullrequest/3",
                        "labels": [], "updated": "2026-03-01", "item_keys": ["AA-12"]}


@pytest.mark.parametrize("status, words", [
    (401, "The operator must fix the token"),
    (404, "The operator must fix the repository or the token's access"),
    (429, "Wait a few minutes"),
])
def test_a_failure_tells_the_agent_what_to_do(status, words):
    fake = FakeAzureDevOps()
    fake.fail = (status, "{}")
    with pytest.raises(IssuesFailure, match=words):
        reader(fake).find_open_issues()


@pytest.mark.anyio
async def test_the_same_server_serves_this_source_and_says_what_its_entries_are():
    async with Client(build(reader(FakeAzureDevOps([record(1, "[AA-12] One")])))) as client:
        tool, = (await client.list_tools()).tools
        result = await client.call_tool("find_open_issues", {"limit": 5})
    assert tool.name == "find_open_issues" and "open pull requests" in " ".join(tool.description.split())
    assert result.structured_content["issues"][0]["item_keys"] == ["AA-12"]
