"""The setup guide (SETUP.md) stays true to the repo: its links and anchors
resolve, every command it names is a real entry point, the token variables
it names are the templates', and the line it says `describe` ends with is
the one the CLI prints. The README and CLAUDE.md both point to it, since
an agent may arrive at either."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUIDE = (REPO / "SETUP.md").read_text()


def anchors(path: Path) -> set[str]:
    """GitHub's heading anchors: lowercase, punctuation dropped, spaces to dashes."""
    heads = re.findall(r"^#+ (.+)$", path.read_text(), re.M)
    return {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-") for h in heads}


def links() -> list[str]:
    return [t for t in re.findall(r"\]\(([^)\s]+)\)", GUIDE) if not t.startswith(("http://", "https://"))]


@pytest.mark.parametrize("target", links())
def test_every_link_resolves(target):
    path, _, anchor = target.partition("#")
    file = REPO / path if path else REPO / "SETUP.md"
    assert file.exists(), f"SETUP.md links to a missing {path}"
    if anchor:
        assert anchor in anchors(file), f"no #{anchor} in {file.name}"


@pytest.mark.parametrize("module, sub", sorted(set(re.findall(r"python -m ([\w.]+) (\w+)", GUIDE))))
def test_every_command_is_a_real_entry_point(module, sub):
    out = subprocess.run([sys.executable, "-m", module, "--help"], cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert sub in out.stdout, f"`python -m {module}` has no {sub!r}"


def test_the_token_variables_are_the_templates():
    for example in sorted((REPO / "examples" / "boards").glob("*.example.toml")):
        connection = tomllib.loads(example.read_text())["connection"]
        for key in ("token_env", "user_env"):
            if key in connection:
                assert f"`{connection[key]}`" in GUIDE, f"{example.name}'s {key} isn't in SETUP.md"


def test_describe_ends_with_the_line_the_guide_names():
    line = "config fits the board."
    assert f"`{line}`" in GUIDE
    for backend in ("plane", "jira"):
        assert f'"\\n{line}"' in (REPO / "adapters" / backend / "__main__.py").read_text()


def test_the_readme_and_claude_md_point_to_it():
    assert "[SETUP.md](SETUP.md)" in (REPO / "README.md").read_text()
    assert "[SETUP.md](SETUP.md)" in (REPO / "CLAUDE.md").read_text()
