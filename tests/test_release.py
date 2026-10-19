"""One version everywhere a release shows it: pyproject.toml, the plugin
manifest, the CHANGELOG's newest entry and its release link, the README's
status line, and what both MCP servers report to a host. CI runs the
README's two Development commands."""

import json
import re
import tomllib
from pathlib import Path

import pytest
from mcp import Client

from knowledge.mcp_app import build as build_docs
from server.mcp_app import build
from server.service import Boards
from tests.test_service import service

REPO = Path(__file__).resolve().parent.parent
VERSION = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
CHANGELOG = (REPO / "CHANGELOG.md").read_text()
README = (REPO / "README.md").read_text()
CI = (REPO / ".github" / "workflows" / "test.yml").read_text()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_the_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)


def test_the_plugin_manifest_has_the_same_version():
    assert json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())["version"] == VERSION


def test_the_changelog_s_newest_entry_is_this_version_with_its_release_link():
    entries = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", CHANGELOG, re.M)
    assert entries and entries[0] == VERSION
    assert f"\n[{VERSION}]: https://github.com/ChrisKornaros/agentic_administration/releases/tag/v{VERSION}\n" in CHANGELOG


def test_the_readme_names_the_release():
    assert f"> **Status: {VERSION}" in README


@pytest.mark.anyio
async def test_both_servers_report_the_version_to_a_host():
    svc, _, _ = service()
    async with Client(build(Boards([svc])), mode="legacy") as client:
        assert client.server_info.version == VERSION
    async with Client(build_docs(None), mode="legacy") as client:
        assert client.server_info.version == VERSION


def test_ci_runs_the_readme_s_commands_on_every_push_and_pull_request():
    assert re.search(r"^  push:\n    branches: \[main\]\n  pull_request:\n", CI, re.M)
    assert re.findall(r"^      - run: (.+)$", CI, re.M) == ["uv sync --locked", "uv run pytest"]
    assert "uv sync " in README and "uv run pytest " in README  # the Development block, with its comments
