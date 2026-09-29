"""Publish a git tree of Markdown to Confluence, one way (design:
agentic_optimization_research roadmap/14 §9 Phase 6b, D26–D28).

Git stays the source, and its history the version control; Confluence is
where non-engineers and agents read it. Every folder becomes a page whose
body is its `index.md` (or else its `README.md`), and every other `.md` file
a page under its folder's page. The root folder's page goes under the
configured parent page. Nothing is deleted (D28): a page whose file is gone
is reported as an orphan, for a person to archive.

A page this tool made carries two labels, the shared one (`publish.label`)
and its file's own (`file_label`, so CQL finds one file's page), plus the
`md-source` property: its source path, the hash of what was last written and
the page version that write made. The property is what pins a page to its
file. A run looks for its pages under the configured parent in the page
listing, which already holds a page written a moment ago, and by the shared
label through CQL, which also finds a page someone moved elsewhere but reads
a search index that can lag a write (as Jira's did, Phase 5). A page is this
tree's only if it carries the shared label; for a page CQL did not return,
that is read from the page itself, not the index. So trees may share a
parent page, but never a label.

A run reads first, then writes in two passes, since a link needs its
target's page id:

1. place: create each missing page with an empty body under its folder's page;
2. write: render each page (Markdown → ADF, a relative link into the tree →
   that page's URL) and PUT it at version + 1, unless the hash of its title,
   parent and body matches the property's, when nothing is written.

Only pages carrying the property are ever written, and never the space
homepage or the configured parent. A dry run (the default) reads and plans
the same way without writing. `max_writes` caps the page creates and updates
of a run; what it leaves out is reported as deferred, and the next run picks
it up.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from adapters.base import AdapterError, NotFound, ValidationError
from adapters.jira import adf
from knowledge.config import KnowledgeConfig
from knowledge.confluence import Confluence, Space, page_version

PROPERTY = "md-source"
INDEX_NAMES = ("index.md", "README.md")  # a folder's own page, the first one present
ROOT = "./"

_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
_H1 = re.compile(r"^#\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LINK = re.compile(r"`[^`]*`|(?P<img>!?)\[(?P<text>[^\]]*)\]\((?P<href>[^)\s]+)\)")  # a code span is left alone
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


@dataclass
class Node:
    """One page of the tree. `key` is its source path: a file `guides/setup.md`,
    a folder `guides/`, the root `./`."""

    key: str
    parent: str | None  # its folder's key; None for the root
    source: Path | None = None  # the Markdown file (a folder's index); None for a folder without one
    title: str = ""
    page_id: str | None = None
    version: int = 0
    prop: dict[str, Any] | None = None  # its md-source property, as last read or written
    created: bool = False  # by this run


@dataclass(frozen=True)
class Entry:
    action: str  # create | update | unchanged | orphan | drift | skip | deferred | conflict | warn
    key: str
    title: str = ""
    note: str = ""


@dataclass
class Report:
    applied: bool
    entries: list[Entry] = field(default_factory=list)
    writes: int = 0  # page creates + updates, made or (dry run) planned
    error: str | None = None  # what stopped the run early

    def add(self, action: str, key: str, title: str = "", note: str = "") -> None:
        self.entries.append(Entry(action, key, title, note))

    def counts(self) -> Counter[str]:
        return Counter(e.action for e in self.entries)

    @property
    def ok(self) -> bool:
        return self.error is None and not any(e.action in ("skip", "conflict") for e in self.entries)


def file_label(label: str, key: str) -> str:
    """A page's own label (D26), from its source path."""
    return f"{label}-{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def walk(root: Path) -> dict[str, Node]:
    """The tree's pages by key, each folder before what it holds. Dot-folders are left out."""
    files = sorted(p for p in root.rglob("*.md")
                   if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts))
    present = set(files)
    nodes: dict[str, Node] = {}

    def folder(d: Path) -> str:
        rel = d.relative_to(root).as_posix()
        key = ROOT if rel == "." else rel + "/"
        if key not in nodes:
            nodes[key] = Node(key, None if d == root else folder(d.parent))
        return key

    for f in files:
        home = folder(f.parent)
        if f == next((f.parent / n for n in INDEX_NAMES if f.parent / n in present), None):
            nodes[home].source = f
        else:
            nodes[f.relative_to(root).as_posix()] = Node(f.relative_to(root).as_posix(), home, f)
    depth = lambda key: 0 if key == ROOT else key.rstrip("/").count("/") + 1
    return dict(sorted(nodes.items(), key=lambda kv: (depth(kv[0]), kv[0])))


def _read(source: Path) -> tuple[str | None, str]:
    """A file's first `# ` heading, as plain text for its title, and its body
    with the front matter and that heading taken out."""
    text = _FRONT_MATTER.sub("", source.read_text(encoding="utf-8").replace("\r\n", "\n"), count=1)
    lines, fenced = text.split("\n"), False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced and (m := _H1.match(line)):
            title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1)).replace("`", "").replace("**", "").strip()
            if title:
                return title, "\n".join(lines[:i] + lines[i + 1:])
    return None, text


def _hash(title: str, parent_id: str, doc: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([title, parent_id, doc], sort_keys=True).encode()).hexdigest()


def publish(root: Path, cfg: KnowledgeConfig, client: Confluence, *, apply: bool = False,
            max_writes: int | None = None) -> Report:
    """Read the space, then place and write the tree, or only plan it unless
    `apply`. An `AdapterError` that stops the run lands in `report.error`,
    after what was already done."""
    run = _Run(root, cfg, client, Report(applied=apply), cfg.max_writes if max_writes is None else max_writes)
    try:
        run.go()
    except AdapterError as exc:
        run.report.error = f"{type(exc).__name__}: {exc}"
    return run.report


class _Run:
    def __init__(self, root: Path, cfg: KnowledgeConfig, client: Confluence, report: Report, cap: int) -> None:
        self.root, self.cfg, self.client, self.report, self.cap = root, cfg, client, report, cap
        self.nodes = walk(root)
        self.space: Space
        self.listing: dict[str, dict[str, Any]] = {}
        self.targets: dict[str, str] = {}  # link path -> node key, for pass 2

    def go(self) -> None:
        self.space = self.client.space(self.cfg.space)
        self.listing = {str(p["id"]): p for p in self.client.pages(self.space.id)}
        if self.cfg.parent not in self.listing:  # read-proven before any write
            raise NotFound(f"space.parent {self.cfg.parent} is not a page in space {self.space.key}")
        self._match()
        mine = {n.page_id for n in self.nodes.values() if n.page_id}
        self._titles({str(p.get("title") or "").casefold() for pid, p in self.listing.items() if pid not in mine})
        self._place()
        self._write()

    def _parent_id(self, n: Node) -> str | None:
        return self.cfg.parent if n.parent is None else self.nodes[n.parent].page_id

    def _under(self, top: str) -> set[str]:
        """The ids of every listed page below `top`."""
        kids: dict[str, list[str]] = {}
        for pid, p in self.listing.items():
            kids.setdefault(str(p.get("parentId") or ""), []).append(pid)
        found, todo = set(), [top]
        while todo:
            for pid in kids.get(todo.pop(), []):
                if pid not in found:
                    found.add(pid)
                    todo.append(pid)
        return found

    def _match(self) -> None:
        """Pin each page this tool made to its node, by the md-source property; report the rest."""
        labelled = set(self.client.labelled(self.space.key, self.cfg.label))
        # oldest first, by createdAt: page ids are not in creation order (the conformance run, 2026-09-28)
        oldest = lambda i: (str((self.listing.get(i) or {}).get("createdAt") or ""), len(i), i)
        for pid in sorted(self._under(self.cfg.parent) | labelled, key=oldest):
            page = self.listing.get(pid)
            if page is None or page.get("status", "current") != "current":  # archived: a person's call, done
                continue
            prop = self.client.property(pid, PROPERTY)
            value = (prop or {}).get("value")
            if not isinstance(value, dict) or not value.get("path"):
                continue  # not ours: a page someone added under the tree
            if pid not in labelled and self.cfg.label not in self.client.labels(pid):
                continue  # another tree's, under the same parent (the read gate, 2026-09-28)
            path, title = str(value["path"]), str(page.get("title") or "")
            node = self.nodes.get(path)
            if node is None or node.page_id is not None:
                why = "its file is gone" if node is None else "a second page for this file"
                self.report.add("orphan", path, title, f"{why}; archive it by hand: {self.space.page_url(pid)}")
                continue
            node.page_id, node.prop, node.version = pid, prop, page_version(page)
            if value.get("version") != node.version:
                self.report.add("drift", path, title, f"edited in Confluence since it was published "
                                f"(v{value.get('version')} → v{node.version}); the next change to its file replaces that")

    def _titles(self, taken: set[str]) -> None:
        """Each node's title: its first heading, or else its file or folder
        name. Titles are unique in a space (case aside), so one that another
        page holds, or that several files share, gets its folder added; one
        taken even then is skipped."""
        base: dict[str, str] = {}
        for n in self.nodes.values():
            heading = _read(n.source)[0] if n.source else None
            name = PurePosixPath(n.key).name if n.key.endswith("/") else PurePosixPath(n.key).stem
            base[n.key] = heading or (self.root.resolve().name if n.key == ROOT else name)
        shared = Counter(t.casefold() for t in base.values())
        used = set(taken)
        for n in self.nodes.values():
            title = base[n.key]
            if shared[title.casefold()] > 1 or title.casefold() in used:
                title = f"{title} ({posixpath.dirname(n.key.rstrip('/')) or self.root.resolve().name})"
            if title.casefold() in used:
                self.report.add("skip", n.key, title, "the title is taken in the space")
                continue
            used.add(title.casefold())
            n.title = title

    def _place(self) -> None:
        """Pass 1: create each missing page, empty, under its folder's page."""
        unplaced: dict[str, str] = {}  # key -> skip | deferred, so what is under it follows
        for n in self.nodes.values():
            if n.page_id:
                continue
            parent_id = self._parent_id(n)
            if not n.title:
                unplaced[n.key] = "skip"  # reported by _titles
                continue
            if parent_id is None:
                unplaced[n.key] = "deferred" if unplaced.get(n.parent or "") == "deferred" else "skip"
                self.report.add(unplaced[n.key], n.key, n.title, "its folder's page is not placed")
                continue
            if self.report.writes >= self.cap:
                unplaced[n.key] = "deferred"
                self.report.add("deferred", n.key, n.title, f"the write cap ({self.cap}) is reached")
                continue
            empty = adf.empty()
            if self.report.applied:
                try:
                    page = self.client.create_page(self.space.id, parent_id, n.title, empty)
                except ValidationError as exc:
                    unplaced[n.key] = "skip"
                    self.report.add("conflict", n.key, n.title, str(exc))
                    continue
                n.page_id, n.version = str(page["id"]), page_version(page)
                # the labels first, so a page with the property always carries them
                self.client.add_labels(n.page_id, [self.cfg.label, file_label(self.cfg.label, n.key)])
                value = {"path": n.key, "hash": _hash(n.title, parent_id, empty), "version": n.version}
                n.prop = self.client.set_property(n.page_id, PROPERTY, value, None)
            else:
                n.page_id, n.version = f"new-{self.report.writes + 1}", 1
                n.prop = {"value": {"hash": _hash(n.title, parent_id, empty)}}
            n.created = True
            self.report.writes += 1
            self.report.add("create", n.key, n.title)

    def _write(self) -> None:
        """Pass 2: write each placed page at version + 1, unless its hash says nothing changed."""
        protected = {self.space.homepage_id, self.cfg.parent}
        self.targets = self._targets()
        for n in self.nodes.values():
            parent_id = self._parent_id(n)
            if not (n.page_id and n.title and parent_id):
                continue
            if n.page_id in protected:
                self.report.add("skip", n.key, n.title, "refusing to write the space homepage or the configured parent")
                continue
            doc = self._render(n)
            digest = _hash(n.title, parent_id, doc)
            if ((n.prop or {}).get("value") or {}).get("hash") == digest:
                if not n.created:
                    self.report.add("unchanged", n.key, n.title)
                continue
            if self.report.writes >= self.cap:
                self.report.add("deferred", n.key, n.title, f"the write cap ({self.cap}) is reached")
                continue
            if self.report.applied:
                try:
                    page = self.client.update_page(n.page_id, parent_id, n.title, doc, n.version + 1)
                except ValidationError as exc:  # a version conflict, a title taken meanwhile
                    self.report.add("conflict", n.key, n.title, str(exc))
                    continue
                n.version = page_version(page, n.version + 1)
                value = {"path": n.key, "hash": digest, "version": n.version}
                n.prop = self.client.set_property(n.page_id, PROPERTY, value, n.prop)
            self.report.writes += 1
            if not n.created:
                self.report.add("update", n.key, n.title)

    def _targets(self) -> dict[str, str]:
        """Every path a relative link may name, from the root → the node it lands on."""
        out: dict[str, str] = {}
        for n in self.nodes.values():
            if n.source is not None:
                out[n.source.relative_to(self.root).as_posix()] = n.key
            if n.key.endswith("/"):
                out["." if n.key == ROOT else n.key.rstrip("/")] = n.key
        return out

    def _render(self, n: Node) -> dict[str, Any]:
        """The page body: the file's Markdown as ADF, with a relative link to a
        file or folder of the tree pointing at its page. A link out of the tree
        and an image (not published) keep only their text, with a warning."""
        if n.source is None:
            return adf.empty()
        _, body = _read(n.source)
        here = posixpath.dirname(n.source.relative_to(self.root).as_posix())

        def link(m: re.Match[str]) -> str:
            href, text = m.group("href"), m.group("text")
            if href is None:  # a code span
                return m.group(0)
            if m.group("img"):
                self.report.add("warn", n.key, n.title, f"image {href} is not published; its alt text stays")
                return text
            if _SCHEME.match(href) or href.startswith(("#", "/")):
                return m.group(0)
            key = self.targets.get(posixpath.normpath(posixpath.join(here, href.split("#", 1)[0])))
            page_id = self.nodes[key].page_id if key else None
            if page_id is None:
                why = "its page is not placed" if key else "it is not a file or folder of this tree"
                self.report.add("warn", n.key, n.title, f"link to {href}: {why}; its text stays")
                return text
            return f"[{text}]({self.space.page_url(page_id)})"

        lines, fenced = [], False
        for line in body.split("\n"):
            fence = _FENCE.match(line) is not None
            fenced = fenced != fence
            lines.append(line if fenced or fence else _LINK.sub(link, line))
        return adf.render("\n".join(lines))
