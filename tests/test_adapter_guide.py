"""The adapter guide (adapters/README.md) stays true to adapters/base.py: it
names every abstract member and every error, and each place a new backend
is wired in exists under the name the guide gives it. No adapter deletes:
the one DELETE anywhere is ClickUp taking a tag off a task."""

import inspect
import re
from pathlib import Path

import pytest

from adapters import base
from adapters.clickup import ClickUpAdapter, transport
from adapters.jira import JiraAdapter
from adapters.plane import PlaneAdapter
from conformance import __main__ as conformance_cli
from conformance import runner
from server import __main__ as server_cli
from server import config

REPO = Path(__file__).resolve().parent.parent
GUIDE = (REPO / "adapters" / "README.md").read_text()

# The wiring checklist: each file, and the names in it a new backend extends.
WIRING = {
    "server/config.py": (config, ["Backend", "CONNECTION_KEYS"]),
    "server/__main__.py": (server_cli, ["make_adapter"]),
    "conformance/__main__.py": (conformance_cli, ["HARNESSES"]),
    "conformance/runner.py": (runner, ["cases_for"]),
}


def named(name: str) -> bool:
    return f"`{name}`" in GUIDE


def test_the_guide_names_every_abstract_member():
    assert base.Adapter.__abstractmethods__
    assert sorted(m for m in base.Adapter.__abstractmethods__ if not named(m)) == []


def test_the_guide_names_every_error():
    errors = [cls.__name__ for _, cls in inspect.getmembers(base, inspect.isclass) if issubclass(cls, base.AdapterError)]
    assert "AdapterError" in errors and len(errors) > 1
    assert [e for e in errors if not named(e)] == []


@pytest.mark.parametrize("path", WIRING, ids=str)
def test_the_wiring_checklist_names_what_exists(path):
    module, names = WIRING[path]
    assert (REPO / path).is_file() and f"`{path}`" in GUIDE
    for name in names:
        assert hasattr(module, name), f"{path} has no {name}"
        assert named(name), f"the guide doesn't name {name}"


def test_no_adapter_deletes():
    # ClickUp takes a tag off a task with a DELETE, and has no other way: one call in the adapter, and one
    # line in its transport that refuses every other DELETE. Any more, or one anywhere else, fails here.
    one_each = {REPO / "adapters" / "clickup" / "adapter.py", REPO / "adapters" / "clickup" / "transport.py"}
    for path in (REPO / "adapters").rglob("*.py"):
        assert len(re.findall(r"""['"]DELETE['"]""", path.read_text())) == (1 if path in one_each else 0), path
    untag = transport.UNTAG
    assert transport.allowed("DELETE", "/task/86c1/tag/needs%20review") and untag.pattern == r"^/task/[^/]+/tag/[^/]+$"
    for path in ("/task/86c1", "/list/9301", "/list/9301/task/86c1", "/space/9101/tag/frontend", "/task/86c1/comment/1"):
        assert not transport.allowed("DELETE", path), path
    for adapter in (PlaneAdapter, JiraAdapter, ClickUpAdapter):
        assert not [n for n in dir(adapter) if "delete" in n.lower() or "remove" in n.lower()], adapter
