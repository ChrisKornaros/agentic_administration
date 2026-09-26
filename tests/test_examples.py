"""The Hermes reference wiring in examples/hermes/: it exposes exactly the
server's eleven tools, and its persona is the README's framing line, so both
hosts frame the agent the same way."""

import re
from pathlib import Path

from tests.test_mcp_app import TOOLS

ROOT = Path(__file__).resolve().parents[1]
HERMES = ROOT / "examples" / "hermes"


def test_hermes_includes_exactly_the_server_tools():
    text = (HERMES / "config.fragment.yaml").read_text()
    include = re.search(r"include: \[([^\]]*)\]", text)
    assert include, "no tools.include list"
    assert set(re.findall(r"[a-z_]+", include.group(1))) == TOOLS


def test_hermes_soul_is_the_readme_framing_line():
    line = (HERMES / "SOUL.md").read_text().strip()
    assert f'--append-system-prompt "{line}"' in (ROOT / "README.md").read_text()
