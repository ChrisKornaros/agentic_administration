"""The repo is public-bound (roadmap/14 D9, §10 item 4): nothing tracked may
hold a secret, a live board's id or board content. The board configs, probe
and conformance reports, raw transcripts and the session hand-off are gitignored; these checks
catch one forced in with `git add -f`, a pasted token, or a real id copied
into a doc. The fakes' ids are made up, never a random (version 4) UUID."""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

PRIVATE_PATHS = re.compile(
    r"^(boards|conformance/reports|transcripts/raw)/|^probes/.*-report\.json$|\.env$|^\.claude/next-session\.md$"
)
SECRETS = {
    "Plane API key": r"plane_api_[0-9a-f]{32}",
    "Atlassian API token": r"ATATT3[A-Za-z0-9_=-]{100,}",
    "Anthropic API key": r"sk-ant-[A-Za-z0-9_-]{40,}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{36}",
    "Discord bot token": r"[MN][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}",
    "Bitwarden session": r"BW_SESSION=[\"']?[A-Za-z0-9+/]{40,}",
}
LIVE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.IGNORECASE)
SITE = re.compile(r"([a-z0-9-]+)\.atlassian\.net")


def tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [p for p in out.decode().split("\0") if p]


def texts() -> dict[str, str]:
    return {p: (REPO / p).read_text(errors="ignore") for p in tracked() if (REPO / p).is_file()}


def test_no_board_content_or_env_file_is_tracked():
    assert [p for p in tracked() if PRIVATE_PATHS.search(p)] == []


def test_no_secret_is_tracked():
    hits = [(p, kind) for p, text in texts().items() for kind, pattern in SECRETS.items() if re.search(pattern, text)]
    assert hits == []


def test_ids_and_sites_are_placeholders():
    found = texts().items()
    assert [(p, m) for p, text in found for m in LIVE_ID.findall(text)] == []
    assert {m for _, text in found for m in SITE.findall(text)} <= {"example", "x"}
