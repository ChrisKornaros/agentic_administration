"""The read side of the published docs (Phase 6b step 4): `Docs` and the
`knowledge` MCP server, offline against the fake Confluence. A tree is
published first, as a team's CI would, then searched and read. The stdio
entry point is tested through the plugin's own command, in
tests/test_examples.py."""

import re
from pathlib import Path

import pytest
from mcp import Client

from adapters.base import AuthError
from knowledge.confluence import Confluence
from knowledge.docs import MAX_K, Docs, DocsFailure
from knowledge.mcp_app import build
from tests.fake_confluence import BASE, KEY, FakeConfluence
from tests.test_knowledge import config, run, tree

ROOT = Path(__file__).resolve().parents[1]
DOC_TOOLS = {"search_docs", "get_doc"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def published(tmp_path) -> tuple[Docs, FakeConfluence]:
    fake = FakeConfluence()
    run(tree(tmp_path), fake)
    return Docs(config(fake), Confluence(fake)), fake


def page_url(fake, title):
    return f"{BASE}/spaces/{KEY}/pages/{fake.by_title(title)['id']}"


def searches(fake, since=0):
    return [params for method, path, params, _ in fake.calls[since:] if path == "/wiki/rest/api/search"]


# -- search_docs ---------------------------------------------------------------------------


def test_search_finds_published_pages_best_first_as_plain_text(tmp_path):
    docs, fake = published(tmp_path)
    hits = docs.search_docs("setup uv sync")
    assert hits[0] == {"id": fake.by_title("Setup")["id"], "title": "Setup", "url": page_url(fake, "Setup"),
                       "excerpt": hits[0]["excerpt"]}
    assert "uv sync" in hits[0]["excerpt"] and not any("@@@" in h["excerpt"] + h["title"] for h in hits)
    assert "Handbook" in [h["title"] for h in hits]  # it links to setup too, so it matches less


def test_search_keeps_to_the_published_pages(tmp_path):
    docs, fake = published(tmp_path)
    fake.add_page("Setup notes", labels=("other",))  # someone else's page in the same space
    since = len(fake.calls)
    titles = [h["title"] for h in docs.search_docs("setup")]
    assert "Setup notes" not in titles and "Setup" in titles
    [params] = searches(fake, since)
    assert params["cql"] == 'space = "KB" and type = page and label = "md-published" and siteSearch ~ "setup"'


def test_a_query_is_quoted_whatever_it_holds(tmp_path):
    docs, fake = published(tmp_path)
    since = len(fake.calls)
    assert docs.search_docs('setup and "uv" \\ (sync)')[0]["title"] == "Setup"  # the fake refuses CQL it can't parse
    assert searches(fake, since)[0]["cql"].endswith('siteSearch ~ "setup and \\"uv\\" \\\\ (sync)"')


def test_k_is_bounded_and_an_empty_query_is_refused(tmp_path):
    docs, fake = published(tmp_path)
    since = len(fake.calls)
    docs.search_docs("setup", k=0)
    docs.search_docs("setup", k=500)
    assert [p["limit"] for p in searches(fake, since)] == [1, MAX_K]
    with pytest.raises(DocsFailure, match="query is empty"):
        docs.search_docs("  ")


def test_excerpts_lose_their_markers_and_entities(tmp_path):
    fake = FakeConfluence()
    run(tree(tmp_path, {"README.md": "# Rules\n\nFish & chips < 5 minutes.\n"}), fake)
    [hit] = Docs(config(fake), Confluence(fake)).search_docs("chips")
    assert hit["excerpt"] == "Fish & chips < 5 minutes."


# -- get_doc -------------------------------------------------------------------------------


def test_get_doc_reads_a_page_as_markdown_by_id_or_url(tmp_path):
    docs, fake = published(tmp_path)
    setup = fake.by_title("Setup")
    doc = docs.get_doc(setup["id"])
    assert (doc["id"], doc["title"], doc["url"], doc["version"]) == (setup["id"], "Setup", page_url(fake, "Setup"), 2)
    assert "| 1 | `uv sync` |" in doc["markdown"]
    assert f"[the handbook]({page_url(fake, 'Handbook')})" in doc["markdown"]  # a link is a page URL get_doc takes
    assert docs.get_doc(page_url(fake, "Handbook"))["title"] == "Handbook"
    assert docs.get_doc(page_url(fake, "Handbook") + "/Handbook")["title"] == "Handbook"  # a webui link's slug


def test_get_doc_refuses_what_was_not_published(tmp_path):
    docs, fake = published(tmp_path)
    private = fake.add_page("Private", labels=("other",))
    with pytest.raises(DocsFailure, match="not one of the published docs"):
        docs.get_doc(private["id"])
    fake.by_title("todo")["status"] = "archived"
    with pytest.raises(DocsFailure, match="not one of the published docs"):
        docs.get_doc(fake.by_title("todo")["id"])
    with pytest.raises(DocsFailure, match="not a page id or a page URL"):
        docs.get_doc("the setup page")
    with pytest.raises(DocsFailure, match="Not found"):
        docs.get_doc("999999")


def test_failures_say_what_to_do_and_nothing_is_written(tmp_path):
    docs, fake = published(tmp_path)
    since = len(fake.calls)
    docs.search_docs("setup")
    docs.get_doc(fake.by_title("Setup")["id"])
    assert fake.writes(since) == []
    fake.fail["GET /wiki/rest/api/search"] = AuthError("HTTP 401 on GET /wiki/rest/api/search: refused")
    with pytest.raises(DocsFailure, match="operator must fix the token"):
        docs.search_docs("setup")


# -- the knowledge MCP server --------------------------------------------------------------


def check_surface(tools) -> None:
    assert {tool.name for tool in tools} == DOC_TOOLS
    assert all(tool.annotations.read_only_hint for tool in tools)


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_exactly_the_two_read_only_tools(tmp_path, mode):
    docs, _ = published(tmp_path)
    async with Client(build(docs), mode=mode) as client:
        tools = (await client.list_tools()).tools
    check_surface(tools)
    [search] = [t for t in tools if t.name == "search_docs"]
    assert f"at most {MAX_K}" in search.description


@pytest.mark.anyio
async def test_search_then_read_over_mcp(tmp_path):
    docs, fake = published(tmp_path)
    async with Client(build(docs)) as client:
        found = await client.call_tool("search_docs", {"query": "setup", "k": 3})
        hit = found.structured_content["results"][0]
        read = await client.call_tool("get_doc", {"ref": hit["url"]})
        refused = await client.call_tool("get_doc", {"ref": "nope"})
    assert not found.is_error and hit["title"] == "Setup"
    assert not read.is_error and "uv sync" in read.structured_content["markdown"]
    assert refused.is_error and "search_docs returned" in refused.content[0].text


@pytest.mark.anyio
async def test_no_docs_configured_means_no_tools():
    async with Client(build(None)) as client:
        assert (await client.list_tools()).tools == []


def test_no_tool_or_client_method_writes():
    source = (ROOT / "knowledge" / "docs.py").read_text()
    calls = set(re.findall(r"self\.client\.(\w+)\(", source))
    assert calls == {"space", "search", "page", "labels"}
