"""The Markdown → Confluence publisher (Phase 6b), offline against the fake:
the tree, the two passes, idempotency, links, the cap, titles, orphans, and no
delete anywhere."""

import re
import shlex
from dataclasses import replace
from pathlib import Path

import pytest

from adapters.base import AuthError, ValidationError
from knowledge import __main__ as cli
from knowledge.__main__ import main, summary
from knowledge.config import InvalidKnowledgeConfig, KnowledgeConfig, from_dict, load
from knowledge.confluence import Confluence
from knowledge.publish import ROOT, Report, file_label, publish, walk
from tests.fake_confluence import BASE, HOME, KEY, SITE, FakeConfluence

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "knowledge" / "confluence.example.toml"
WORKFLOW = REPO / "examples" / "knowledge" / "publish-docs.yml"

DOCS = {
    "README.md": "# Handbook\n\nStart with [setup](guides/setup.md) and [the guides](guides/).\n",
    "guides/index.md": "---\ntags: [docs]\n---\n# Guides\n\nSee [install](setup.md#install).\n",
    "guides/README.md": "# Guides readme\n\nindex.md wins, so this is a page of its own.\n",
    "guides/setup.md": "# Setup\n\n| step | what |\n| --- | --- |\n| 1 | `uv sync` |\n\n"
                       "Back to [the handbook](../README.md).\n\n```md\n[not a link](nowhere.md)\n```\n",
    "notes/deep/todo.md": "no heading here\n",
    ".hidden/skip.md": "# Hidden\n",
}


def tree(tmp_path, files=DOCS) -> Path:
    root = tmp_path / "docs"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def config(fake, **kw) -> KnowledgeConfig:
    return KnowledgeConfig("JIRA_API_TOKEN", "JIRA_USER", SITE, KEY, fake.parent, **kw)


def run(root, fake, *, apply=True, **kw):
    return publish(root, config(fake), Confluence(fake), apply=apply, **kw)


def actions(report, action):
    return sorted(e.key for e in report.entries if e.action == action)


def links(doc):
    """Every link href in an ADF doc, in order."""
    found = []

    def visit(node):
        for mark in node.get("marks") or []:
            if mark["type"] == "link":
                found.append(mark["attrs"]["href"])
        for child in node.get("content") or []:
            visit(child)

    visit(doc)
    return found


def url(fake, title):
    return f"{BASE}/spaces/{KEY}/pages/{fake.by_title(title)['id']}"


# -- the tree ------------------------------------------------------------------------------


def test_walk_makes_each_folder_a_page_with_its_index_as_the_body(tmp_path):
    root = tree(tmp_path)
    nodes = walk(root)
    assert list(nodes) == [ROOT, "guides/", "notes/", "guides/README.md", "guides/setup.md", "notes/deep/",
                           "notes/deep/todo.md"]  # each folder before what it holds; dot-folders left out
    assert nodes[ROOT].source == root / "README.md" and nodes[ROOT].parent is None
    assert nodes["guides/"].source == root / "guides" / "index.md"
    assert nodes["guides/setup.md"].parent == "guides/"
    assert nodes["notes/"].source is None and nodes["notes/deep/"].parent == "notes/"


def test_a_dry_run_reads_and_plans_but_writes_nothing(tmp_path):
    fake = FakeConfluence()
    report = run(tree(tmp_path), fake, apply=False)
    assert fake.writes() == [] and report.ok and not report.applied
    assert len(actions(report, "create")) == 7
    assert report.writes == 7 + 5  # 7 pages; all but the 2 bare folders have a body to write


def test_the_first_publish_builds_the_tree_under_the_parent(tmp_path):
    fake = FakeConfluence()
    report = run(tree(tmp_path), fake)
    assert report.ok and report.error is None
    parent = lambda title: fake.pages[fake.by_title(title)["parentId"]]["title"]
    assert parent("Handbook") == "Docs"
    assert parent("Guides") == parent("notes") == "Handbook"
    assert parent("Setup") == parent("Guides readme") == "Guides"
    assert parent("deep") == "notes" and parent("todo") == "deep"
    setup = fake.by_title("Setup")
    assert setup["labels"] == {"md-published", file_label("md-published", "guides/setup.md")}
    assert fake.prop("Setup")["value"] == {"path": "guides/setup.md", "hash": fake.prop("Setup")["value"]["hash"],
                                           "version": 2}  # created empty (v1), then written (v2)
    blocks = fake.doc("Setup")["content"]
    assert [b["type"] for b in blocks] == ["table", "paragraph", "codeBlock"]  # the H1 is the title, not the body
    assert [b["type"] for b in fake.doc("Guides")["content"]] == ["paragraph"]  # no front matter
    assert fake.by_title("notes")["version"]["number"] == 1  # a bare folder is never rewritten


def test_relative_links_become_page_urls(tmp_path):
    fake = FakeConfluence()
    run(tree(tmp_path), fake)
    assert links(fake.doc("Handbook")) == [url(fake, "Setup"), url(fake, "Guides")]
    assert links(fake.doc("Guides")) == [url(fake, "Setup")]  # the #fragment is dropped
    assert links(fake.doc("Setup")) == [url(fake, "Handbook")]  # not the one in the code block
    assert "[not a link](nowhere.md)" in fake.doc("Setup")["content"][2]["content"][0]["text"]


def test_a_rerun_writes_nothing(tmp_path):
    fake, root = FakeConfluence(), tree(tmp_path)
    run(root, fake)
    since = len(fake.calls)
    report = run(root, fake)
    assert fake.writes(since) == [] and report.writes == 0 and report.ok
    assert len(actions(report, "unchanged")) == 7


def test_a_rerun_finds_its_pages_even_before_the_search_index_has_them(tmp_path):
    fake, root = FakeConfluence(), tree(tmp_path)
    run(root, fake)
    fake.unindexed.update(fake.pages)  # CQL sees none of them yet
    since = len(fake.calls)
    report = run(root, fake)
    assert fake.writes(since) == [] and len(actions(report, "unchanged")) == 7


def test_a_tree_under_the_same_parent_with_another_label_is_left_alone(tmp_path):
    # the read gate (2026-09-28): a second tree's dry run took the first tree's root as its own
    fake, first = FakeConfluence(), tree(tmp_path)
    run(first, fake)
    fake.unindexed.update(fake.pages)  # so its own re-run below finds its pages by the scan, like the other's
    firsts = set(fake.pages)
    second = tree(tmp_path / "other", {"README.md": "# Runbooks\n", "deploy.md": "# Deploy\n"})
    since = len(fake.calls)
    report = publish(second, config(fake, label="runbooks"), Confluence(fake), apply=True)
    assert report.ok and actions(report, "create") == [ROOT, "deploy.md"]
    assert not [e for e in report.entries if e.action not in ("create", "update")]  # no orphan, drift or skip
    touched = {m.group(1) for _, path in fake.writes(since) if (m := re.search(r"/(?:pages|content)/(\d+)", path))}
    assert not touched & firsts and fake.by_title("Runbooks")["parentId"] == fake.parent
    report = run(first, fake)  # and the first tree, re-run, finds only its own
    assert report.writes == 0 and len(actions(report, "unchanged")) == 7 and not actions(report, "orphan")


def test_an_edit_makes_exactly_one_new_version(tmp_path):
    fake, root = FakeConfluence(), tree(tmp_path)
    run(root, fake)
    (root / "guides" / "setup.md").write_text("# Setup\n\nNow shorter.\n")
    since = len(fake.calls)
    report = run(root, fake)
    setup = fake.by_title("Setup")["id"]
    assert fake.writes(since) == [("PUT", f"/wiki/api/v2/pages/{setup}"),
                                  ("PUT", f"/wiki/api/v2/pages/{setup}/properties/{fake.prop('Setup')['id']}")]
    assert actions(report, "update") == ["guides/setup.md"] and fake.by_title("Setup")["version"]["number"] == 3
    assert fake.prop("Setup")["value"]["version"] == 3


def test_a_removed_file_is_reported_and_nothing_is_deleted(tmp_path):
    fake, root = FakeConfluence(), tree(tmp_path)
    run(root, fake)
    (root / "notes" / "deep" / "todo.md").unlink()
    report = run(root, fake)
    assert actions(report, "orphan") == ["notes/", "notes/deep/", "notes/deep/todo.md"]
    assert all(t in {p["title"] for p in fake.pages.values()} for t in ("notes", "deep", "todo"))
    assert "archive it by hand" in report.entries[0].note and report.ok
    # once a person archives it, it is theirs: no longer reported, but its title still counts as taken
    fake.by_title("todo")["status"] = "archived"
    (root / "todo.md").write_text("# todo\n")
    report = run(root, fake)
    assert "notes/deep/todo.md" not in actions(report, "orphan")
    assert fake.pages[fake.by_title("todo (docs)")["id"]]["parentId"] == fake.by_title("Handbook")["id"]


def test_of_two_pages_for_one_file_the_older_is_kept_though_its_id_is_lower(tmp_path):
    fake, root = FakeConfluence(), tree(tmp_path)
    run(root, fake)
    setup = fake.by_title("Setup")
    # a newer page carrying the same md-source, with a lower id: live ids are not in creation order
    fake.add_page("Setup copy", setup["parentId"], page_id="10", labels=("md-published",),
                  props={"md-source": fake.prop("Setup")["value"]})
    report = run(root, fake)
    assert [(e.key, e.title) for e in report.entries if e.action == "orphan"] == [("guides/setup.md", "Setup copy")]
    assert "a second page for this file" in next(e.note for e in report.entries if e.action == "orphan")
    assert report.writes == 0 and not actions(report, "drift")


def test_no_delete_anywhere(tmp_path):
    for path in (REPO / "knowledge").glob("*.py"):
        assert not re.search(r"""['"]DELETE['"]""", path.read_text()), path
    assert not [name for name in dir(Confluence) if "delete" in name.lower() or "remove" in name.lower()]
    fake, root = FakeConfluence(), tree(tmp_path)
    run(root, fake)
    (root / "guides" / "setup.md").unlink()
    (root / "README.md").write_text("# Handbook\n\nchanged\n")
    run(root, fake)
    assert "DELETE" not in {m for m, _ in fake.log}


# -- the cap, titles, guards, failures ------------------------------------------------------


def test_the_write_cap_defers_the_rest_and_the_next_run_finishes(tmp_path):
    fake, root = FakeConfluence(), tree(tmp_path)
    report = run(root, fake, max_writes=2)
    assert report.writes == 2 and report.ok
    assert actions(report, "create") == [ROOT, "guides/"]
    assert "notes/deep/todo.md" in actions(report, "deferred")  # its folder's page wasn't placed either
    report = run(root, fake)
    assert report.ok and not actions(report, "deferred")
    assert links(fake.doc("Handbook")) == [url(fake, "Setup"), url(fake, "Guides")]


def test_a_title_held_elsewhere_or_shared_gets_its_folder_and_one_taken_even_then_is_skipped(tmp_path):
    fake = FakeConfluence()
    fake.add_page("Setup")  # someone else's page
    root = tree(tmp_path, {**DOCS, "ops/setup.md": "# Runbook\n", "ops/other.md": "# Runbook\n"})
    report = run(root, fake)
    assert {"Setup (guides)", "Runbook (ops)"} <= {p["title"] for p in fake.pages.values()}
    assert actions(report, "skip") == ["ops/setup.md"]  # both want "Runbook (ops)"; the first one has it
    assert not report.ok


def test_it_never_writes_the_homepage_or_the_parent(tmp_path):
    fake = FakeConfluence()
    # a page someone labelled and marked as ours: the root's page would be the homepage
    fake.pages[HOME]["labels"].add("md-published")
    fake._add_prop(HOME, "md-source", {"path": ROOT, "hash": "x", "version": 1})
    report = run(tree(tmp_path), fake)
    assert ("PUT", f"/wiki/api/v2/pages/{HOME}") not in fake.log
    assert "refusing to write the space homepage" in next(e.note for e in report.entries if e.action == "skip")


def test_links_out_of_the_tree_and_images_keep_their_text_with_a_warning(tmp_path):
    fake = FakeConfluence()
    root = tree(tmp_path, {"README.md": "# Home\n\n[license](../LICENSE) ![diagram](img/flow.png) "
                                        "[web](https://example.invalid/x)\n"})
    report = run(root, fake)
    assert fake.doc("Home")["content"][0]["content"][0]["text"] == "license diagram "
    assert links(fake.doc("Home")) == ["https://example.invalid/x"]
    assert [e.note.split(":")[0] for e in report.entries if e.action == "warn"] == [
        "link to ../LICENSE", "image img/flow.png is not published; its alt text stays"]


def test_a_conflict_is_reported_and_the_run_goes_on(tmp_path):
    fake, root = FakeConfluence(), tree(tmp_path)
    run(root, fake)
    for rel in ("README.md", "guides/setup.md"):
        (root / rel).write_text((root / rel).read_text() + "\nmore\n")
    fake.fail[f"PUT /wiki/api/v2/pages/{fake.by_title('Handbook')['id']}"] = ValidationError(
        "HTTP 409 on PUT: Version must be incremented")
    report = run(root, fake)
    assert actions(report, "conflict") == [ROOT] and actions(report, "update") == ["guides/setup.md"]
    assert not report.ok


def test_edits_made_in_confluence_are_reported_as_drift(tmp_path):
    fake, root = FakeConfluence(), tree(tmp_path)
    run(root, fake)
    fake.edit_in_ui("Setup")
    report = run(root, fake)
    assert actions(report, "drift") == ["guides/setup.md"] and report.writes == 0
    (root / "guides" / "setup.md").write_text("# Setup\n\ngit wins\n")
    run(root, fake)
    assert fake.by_title("Setup")["version"]["number"] == 4 and fake.prop("Setup")["value"]["version"] == 4


def test_a_stop_keeps_what_was_done_and_says_why(tmp_path):
    fake = FakeConfluence()
    fake.fail["GET /wiki/api/v2/spaces"] = AuthError("HTTP 401 on GET /wiki/api/v2/spaces: refused")
    report = run(tree(tmp_path), fake)
    assert report.error.startswith("AuthError") and not report.ok and fake.writes() == []


def test_a_parent_outside_the_space_is_refused_before_any_write(tmp_path):
    fake = FakeConfluence()
    report = publish(tree(tmp_path), replace(config(fake), parent="999"), Confluence(fake), apply=True)
    assert "space.parent 999 is not a page" in report.error and fake.writes() == []


# -- config and CLI ---------------------------------------------------------------------------


def test_the_example_config_loads():
    cfg = load(EXAMPLE)
    assert (cfg.token_env, cfg.user_env, cfg.space, cfg.parent, cfg.label, cfg.max_writes) == (
        "JIRA_API_TOKEN", "JIRA_USER", "KB", "123456", "md-published", 50)


def test_the_ci_example_runs_the_real_cli_with_the_example_configs_secrets(tmp_path, monkeypatch):
    text = WORKFLOW.read_text()
    argv = shlex.split(re.search(r"run: (.*python -m knowledge .*)", text).group(1))
    args = argv[argv.index("knowledge") + 1:]
    tree_dir, config_path = args[1], args[args.index("--config") + 1]
    cfg = load(EXAMPLE)
    for env in (cfg.token_env, cfg.user_env):
        assert f"{env}: ${{{{ secrets.{env} }}}}" in text  # the names the config gives, fed from secrets
    assert re.search(r"concurrency:\n  group: publish-docs\n  cancel-in-progress: false", text)
    assert f'"{tree_dir}/**", "{config_path}"' in text  # a push that changes either publishes
    # the command is one the CLI takes, and it writes
    monkeypatch.chdir(tmp_path)
    (tmp_path / tree_dir).mkdir()
    (tmp_path / config_path).write_text(EXAMPLE.read_text())
    seen = {}
    monkeypatch.setattr(cli, "publish", lambda root, cfg, client, *, apply, max_writes:
                        seen.update(root=root, apply=apply) or Report(applied=apply))
    assert cli.main(args) == 0 and seen == {"root": Path(tree_dir), "apply": True}


def test_a_bad_config_lists_every_problem():
    with pytest.raises(InvalidKnowledgeConfig) as exc:
        from_dict({"connection": {"token_env": "ATATT3xFf-0=", "user_env": "JIRA_USER", "site": "x", "token": "t"},
                   "space": {"key": "", "parent": "home"}, "publish": {"label": "Has Space", "max_writes": 0},
                   "extra": {}})
    assert len(exc.value.problems) == 7


def test_the_cli_refuses_a_bad_config_and_sums_up_a_report(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text('[connection]\ntoken = "ATATT-pasted-value"\n')
    assert main(["publish", str(tmp_path), "--config", str(bad)]) == 2
    assert "ATATT" not in capsys.readouterr().err
    report = run(tree(tmp_path), FakeConfluence(), apply=False)
    text = summary(report)
    assert text.startswith("dry run: nothing written") and 'create     guides/setup.md "Setup"' in text
    assert text.endswith("7 create; 12 page write(s) planned")
