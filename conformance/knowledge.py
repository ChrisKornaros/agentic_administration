"""The knowledge publisher's live suite (design: agentic_optimization_research
roadmap/14 §9 Phase 6b, D26–D29): a small Markdown tree published to a
throwaway Confluence space, under a fresh, empty parent page.

  uv run python -m conformance.knowledge boards/<kb>.toml --dry-run   # the cases; no calls
  uv run python -m conformance.knowledge boards/<kb>.toml             # live: real writes, no deletes

The gate: the tree publishes and its links resolve, a re-run writes
nothing, one edit makes exactly one new version, and a removed file is
reported with nothing deleted. On the way it answers what the offline fake
could only take from the docs: how `_links.next` pages each listing,
whether a property write bumps the page version, whether a PUT with
`parentId` moves a page, how long CQL lags a label write (and that a page's
own labels, which the publisher's label check reads, do not), the real 409 and
400 bodies, and whether the page listing holds archived pages and an
archived page's title blocks a new one. That last needs a person: the run
stops (exit 3) for the orphan to be archived by hand, which is how the
design leaves it, and a re-run resumes.

A run's pages carry its own label (`<publish.label>-<run id>`) and titles
(each ends in the run id), so runs never find each other's pages. The run
record goes where the adapter suite's does (reports/, gitignored) and is
resumed the same way (runner.py). Each case rebuilds the tree in a temp
folder from the run id and its stage.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Callable

from adapters.base import ValidationError
from adapters.jira import adf
from adapters.jira.transport import DEFAULT_THROTTLE, JiraTransport
from conformance import runner
from conformance.cases import Case, Failed, NeedsOperator, Skipped, expect, no_delete
from knowledge.config import InvalidKnowledgeConfig, KnowledgeConfig, load
from knowledge.confluence import WIKI, Confluence, Space, page_version
from knowledge.publish import PROPERTY, ROOT, Report, file_label, publish
from server import secrets

REPORTS = Path(__file__).resolve().parent / "reports"
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")  # it goes into a label
BASE, EDIT, MOVE, REMOVE = "base", "edit", "move", "remove"
SETUP, OLD = "guides/setup.md", "guides/old.md"
LAG_LIMIT, LAG_POLL = 180.0, 5.0  # seconds: how long `search` waits for CQL, and how often it asks


def files(run_id: str, stage: str) -> dict[str, str]:
    """The tree at a stage: `edit` changes setup.md once, `move` twice, and `remove` also takes old.md out."""
    r = run_id
    out = {
        "README.md": f"# Conformance {r}\n\nA throwaway tree. Start with [setup](guides/setup.md), [the guides](guides/) "
                     f"or [a note](notes-{r}/todo-{r}.md#top). [Out of the tree](../LICENSE) and ![an image](flow.png) "
                     "keep only their text; [the web](https://example.com/) stays a link.\n",
        "guides/index.md": f"---\ntags: [conformance]\n---\n# Guides {r}\n\nSee [setup](setup.md), or go [back](../README.md).\n",
        SETUP: f"# Setup {r}\n\n| step | what |\n| --- | --- |\n| 1 | `uv sync` |\n\nBack to [the guides](index.md). "
               f"Its note is [[todo-{r}]].\n",
        OLD: f"# Old {r}\n\nThe `remove` case takes this file out.\n",
        f"notes-{r}/todo-{r}.md": "No heading, so the file name is the title. See [[guides]].\n",
    }
    out[SETUP] += "".join(f"\nEdit {n}.\n" for n in range(1, {BASE: 0, EDIT: 1}.get(stage, 2) + 1))
    if stage == REMOVE:
        del out[OLD]
    return out


def expected(run_id: str) -> dict[str, tuple[str, str | None, set[str]]]:
    """Each page's key -> its title, its parent's key (None: the configured parent), and where its links land,
    its [[wikilinks]] and its closing backlinks included."""
    r, note = run_id, f"notes-{run_id}/todo-{run_id}.md"
    return {
        ROOT: (f"Conformance {r}", None, {SETUP, "guides/", note}),
        "guides/": (f"Guides {r}", ROOT, {SETUP, ROOT, note}),
        f"notes-{r}/": (f"notes-{r}", ROOT, set()),
        OLD: (f"Old {r}", "guides/", set()),
        SETUP: (f"Setup {r}", "guides/", {"guides/", note, ROOT}),
        note: (f"todo-{r}", f"notes-{r}/", {"guides/", ROOT, SETUP}),
    }


@dataclass
class KbContext:
    """What a case sees. runner.run drives it as it does the adapter suite's `Context`."""

    client: Confluence
    config: KnowledgeConfig  # its label is this run's own
    run_id: str
    work: Path  # the case's tree is written here
    calls: Callable[[], list[tuple[str, str]]]  # (method, path) sent by this process
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    ids: dict[str, Any] = field(default_factory=dict)  # persisted across resumes
    wire_before: Counter = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)
    _space: Space | None = None

    def note(self, text: str) -> None:
        self.notes.append(text)

    @property
    def space(self) -> Space:
        if self._space is None:
            self._space = self.client.space(self.config.space)
        return self._space

    def page_id(self, key: str) -> str:
        return self.ids[f"page:{key}"]

    def publish(self, stage: str, *, apply: bool = True) -> Report:
        root = self.work / "docs"
        shutil.rmtree(root, ignore_errors=True)
        for rel, text in files(self.run_id, stage).items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        report = publish(root, self.config, self.client, apply=apply)
        expect(report.error is None, f"the publish stopped: {report.error}")
        return report


# --- helpers -----------------------------------------------------------------------


def acts(report: Report, action: str) -> list[str]:
    return sorted(e.key for e in report.entries if e.action == action)


def writes_since(ctx: KbContext, before: int) -> list[tuple[str, str]]:
    return [(m, p) for m, p in ctx.calls()[before:] if m != "GET"]


def listing(ctx: KbContext) -> dict[str, dict[str, Any]]:
    return {str(p["id"]): p for p in ctx.client.pages(ctx.space.id)}


def published(ctx: KbContext) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """This run's current pages by source path, read back apart from the publisher: the
    listing below the parent, then each page's md-source property. Its (row, property)."""
    rows = listing(ctx)
    kids: dict[str, list[str]] = {}
    for pid, p in rows.items():
        kids.setdefault(str(p.get("parentId") or ""), []).append(pid)
    out: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    todo = [ctx.config.parent]
    while todo:
        for pid in kids.get(todo.pop(), []):
            todo.append(pid)
            prop = ctx.client.property(pid, PROPERTY)
            path = ((prop or {}).get("value") or {}).get("path")
            if prop and path and rows[pid].get("status", "current") == "current":
                expect(path not in out, f"two pages carry {path}: {out[path][0]['id'] if path in out else ''} and {pid}")
                out[path] = (rows[pid], prop)
    return out


def links(node: Any) -> list[str]:
    """Every link in an ADF doc: link marks, and any card Confluence turned one into."""
    if not isinstance(node, dict):
        return []
    found = [m["attrs"]["href"] for m in node.get("marks") or [] if m.get("type") == "link"]
    if node.get("type") in ("inlineCard", "blockCard"):
        found.append(str((node.get("attrs") or {}).get("url")))
    return found + [h for child in node.get("content") or [] for h in links(child)]


def _shape(href: str) -> str:
    """A `_links.next` with its cursor and query values elided: its form, not its content."""
    return re.sub(r"=([^&]*)", lambda m: "=…" if m.group(1) else "=", href)


# --- the cases ---------------------------------------------------------------------


def space_check(ctx: KbContext) -> None:
    rows = listing(ctx)
    parent = rows.get(ctx.config.parent)
    expect(parent is not None, f"space.parent {ctx.config.parent} is not a page in space {ctx.space.key}")
    expect(ctx.config.parent != ctx.space.homepage_id, "space.parent is the space homepage; point it at a fresh page")
    statuses = Counter(str(p.get("status")) for p in rows.values())
    ctx.note(f"space {ctx.space.key} (id {ctx.space.id}), homepage {ctx.space.homepage_id}, web base {ctx.space.base}; "
             f"{len(rows)} pages listed ({dict(statuses)}); parent {ctx.config.parent} {parent.get('title')!r}")
    held = [pid for pid, p in rows.items() if str(p.get("parentId")) == ctx.config.parent]
    if held:
        raise NeedsOperator(f"space.parent already holds {len(held)} page(s); make a fresh, empty page, "
                            "point space.parent at it, then re-run")


def first_publish(ctx: KbContext) -> None:
    want = expected(ctx.run_id)
    before = len(ctx.calls())
    dry = ctx.publish(BASE, apply=False)
    expect(not writes_since(ctx, before), f"the dry run wrote: {writes_since(ctx, before)}")
    expect(acts(dry, "create") == sorted(want), f"the dry run plans {acts(dry, 'create')}")
    report = ctx.publish(BASE)
    ctx.ids["published_at"] = ctx.clock()
    expect(report.ok, f"not clean: {[e for e in report.entries if e.action in ('skip', 'conflict')]}")
    expect(acts(report, "create") == sorted(want) and report.writes == dry.writes,
           f"created {acts(report, 'create')} in {report.writes} writes; the dry run planned {dry.writes}")
    ctx.note(f"{len(want)} pages in {report.writes} page writes, as the dry run (no write) planned; warnings: "
             + "; ".join(e.note for e in report.entries if e.action == "warn"))

    pages = published(ctx)
    expect(sorted(pages) == sorted(want), f"read back {sorted(pages)}")
    ids = {key: str(row["id"]) for key, (row, _) in pages.items()}
    ctx.ids.update({f"page:{key}": pid for key, pid in ids.items()})
    for key, (title, parent, _) in want.items():
        row = pages[key][0]
        expect(row.get("title") == title, f"{key} is titled {row.get('title')!r}, not {title!r}")
        under = ctx.config.parent if parent is None else ids[parent]
        expect(str(row.get("parentId")) == under, f"{key} sits under {row.get('parentId')}, not {under}")
    ctx.note("every page has its title and sits under its folder's page")

    ahead = {key: (page_version(row), prop["value"].get("version")) for key, (row, prop) in pages.items()
             if page_version(row) != prop["value"].get("version")}
    ctx.note(f"page version vs md-source version: {ahead} — a property write bumps the page version" if ahead else
             "every page's version equals its md-source version: a property or label write does not bump it")
    expect(not ahead, "the publisher's own property writes would read as drift")

    by_id = {pid: key for key, pid in ids.items()}
    for key, (_, _, targets) in want.items():
        if not targets:
            continue
        page = ctx.client.page(ids[key])
        hrefs = links(page.get("doc"))
        inside = [h for h in hrefs if h.startswith(f"{ctx.space.base}/spaces/")]
        landed = {by_id.get(h.rstrip("/").rsplit("/", 1)[-1], h) for h in inside}
        expect(landed == targets, f"{key} links to {sorted(landed)}, not {sorted(targets)}")
        if key == ROOT:
            expect("https://example.com/" in hrefs, f"the external link is gone: {hrefs}")
            webui = str((page.get("_links") or {}).get("webui") or "")
            expect(webui.startswith(f"/spaces/{ctx.space.key}/pages/{ids[key]}"), f"its webui is {webui!r}")
            ctx.note(f"the root page's own webui is {webui.replace(ids[key], '<id>')}, "
                     "which the publisher's link form is a prefix of")
    ctx.note("every relative link came back as a link mark on the target page's URL; the external one kept its link")


def search_lag(ctx: KbContext) -> None:
    ids = {v for k, v in ctx.ids.items() if k.startswith("page:")}
    expect(ids, "no pages recorded; `publish` runs first")
    stale = sorted(pid for pid in ids if ctx.config.label not in ctx.client.labels(pid))
    expect(not stale, f"the v2 labels route lacks the shared label on {stale} after the publish: "
                      "the subtree scan would pass those pages over")
    ctx.note(f"before any wait, the v2 labels route holds the shared label on all {len(ids)} pages")
    start = float(ctx.ids.get("published_at") or ctx.clock())
    while True:
        found = set(ctx.client.labelled(ctx.config.space, ctx.config.label))
        waited = ctx.clock() - start
        if ids <= found or waited >= LAG_LIMIT:
            break
        ctx.sleep(LAG_POLL)
    if not ids <= found:
        raise Skipped(f"CQL found {len(ids & found)} of {len(ids)} pages by the shared label {waited:.0f}s after the "
                      "publish; the subtree scan covers that, and the file label went unchecked")
    ctx.note(f"CQL found all {len(ids)} pages by the shared label {waited:.0f}s after the publish ended")
    one = ctx.client.labelled(ctx.config.space, file_label(ctx.config.label, SETUP))
    expect(one == [ctx.page_id(SETUP)], f"setup.md's file label finds {one}")
    ctx.note("setup.md's file label finds exactly its page")


def paging(ctx: KbContext) -> None:
    cql = f'space = "{ctx.space.key}" and type = page and label = "{ctx.config.label}"'
    for name, path, params, row_id, full in (
        ("v2 page listing", f"{WIKI}/api/v2/spaces/{ctx.space.id}/pages", {}, lambda r: str(r["id"]), 250),
        ("v1 CQL search", f"{WIKI}/rest/api/search", {"cql": cql}, lambda r: str((r.get("content") or {}).get("id")), 100),
    ):
        first = ctx.client.t.request("GET", path, params={**params, "limit": 1}) or {}
        nxt = str((first.get("_links") or {}).get("next") or "")
        expect(nxt, f"the {name} gave no _links.next at limit 1")
        one = [row_id(r) for r in ctx.client._walk(path, {**params, "limit": 1})]
        whole = [row_id(r) for r in ctx.client._walk(path, {**params, "limit": full})]
        expect(sorted(one) == sorted(whole) and len(set(one)) == len(one),
               f"the {name} walked one row at a time gives {len(one)} rows, {len(whole)} in one call")
        ctx.note(f"{name}: _links.next is {_shape(nxt)}; the walk followed it through {len(one)} rows, "
                 "the same ones a single call returns")


def rerun(ctx: KbContext) -> None:
    before = len(ctx.calls())
    report = ctx.publish(BASE)
    wrote = writes_since(ctx, before)
    expect(not wrote and report.writes == 0, f"the re-run wrote: {wrote}")
    expect(acts(report, "unchanged") == sorted(expected(ctx.run_id)), f"unchanged: {acts(report, 'unchanged')}")
    expect(not acts(report, "drift"), f"drift on {acts(report, 'drift')}: the publisher's own writes read as edits")
    ctx.note(f"no write in {len(ctx.calls()) - before} calls; every page unchanged, none drifted")


def edit(ctx: KbContext) -> None:
    setup = ctx.page_id(SETUP)
    versions = {pid: page_version(p) for pid, p in listing(ctx).items()}
    before = len(ctx.calls())
    report = ctx.publish(EDIT)
    wrote = writes_since(ctx, before)
    expect(acts(report, "update") == [SETUP] and report.writes == 1, f"updated {acts(report, 'update')} "
           f"in {report.writes} page writes")
    expect(len(wrote) == 2 and wrote[0] == ("PUT", f"{WIKI}/api/v2/pages/{setup}") and wrote[1][0] == "PUT"
           and wrote[1][1].startswith(f"{WIKI}/api/v2/pages/{setup}/properties/"), f"wrote {wrote}")
    after = {pid: page_version(p) for pid, p in listing(ctx).items()}
    changed = {pid: (versions.get(pid), v) for pid, v in after.items() if versions.get(pid) != v}
    expect(changed == {setup: (versions[setup], versions[setup] + 1)}, f"versions changed: {changed}")
    prop = ctx.client.property(setup, PROPERTY) or {}
    expect((prop.get("value") or {}).get("version") == after[setup], f"md-source says {prop.get('value')}")
    ctx.note(f"setup.md's page went v{versions[setup]} → v{after[setup]} and no other page changed; "
             "the writes were its PUT and its property's PUT")


def move(ctx: KbContext) -> None:
    setup, root, guides = ctx.page_id(SETUP), ctx.page_id(ROOT), ctx.page_id("guides/")
    page = ctx.client.page(setup)
    ctx.client.update_page(setup, root, str(page["title"]), page["doc"], page_version(page) + 1)
    parent = str(listing(ctx)[setup].get("parentId"))
    ctx.note(f"a v2 PUT naming the root page as parentId {'moved' if parent == root else 'did NOT move'} "
             f"setup.md's page (its parent is now {parent})")
    expect(parent == root, "a v2 PUT does not move a page, so the publisher cannot put one back")
    before = len(ctx.calls())
    report = ctx.publish(EDIT)
    expect(acts(report, "drift") == [SETUP] and report.writes == 0 and not writes_since(ctx, before),
           f"drift on {acts(report, 'drift')}, {report.writes} page writes")
    ctx.note("the publisher found it under the root page, reported it as drift and wrote nothing")
    report = ctx.publish(MOVE)
    expect(acts(report, "update") == [SETUP] and report.writes == 1, f"updated {acts(report, 'update')}")
    parent = str(listing(ctx)[setup].get("parentId"))
    expect(parent == guides, f"after the next edit it sits under {parent}, not the guides page {guides}")
    ctx.note("the next edit to its file put it back under the guides page")


def remove(ctx: KbContext) -> None:
    old = ctx.page_id(OLD)
    before = len(ctx.calls())
    report = ctx.publish(REMOVE)
    expect(acts(report, "orphan") == [OLD] and report.ok, f"orphans {acts(report, 'orphan')}")
    expect(report.writes == 0 and not writes_since(ctx, before), f"wrote {writes_since(ctx, before)}")
    row = listing(ctx).get(old) or {}
    expect(row.get("status") == "current", f"old.md's page is {row.get('status')!r}")
    note = next(e.note for e in report.entries if e.action == "orphan")
    ctx.note(f"reported as an orphan ({note.split(':')[0]}), nothing written, and the page is still current")


def refusals(ctx: KbContext) -> None:
    root = ctx.page_id(ROOT)
    page = ctx.client.page(root)
    for what, attempt in (
        ("a PUT at the current version, not the next",
         lambda: ctx.client.update_page(root, ctx.config.parent, str(page["title"]), page["doc"], page_version(page))),
        ("a create with a title the space holds",
         lambda: ctx.client.create_page(ctx.space.id, root, str(page["title"]), adf.empty())),
    ):
        try:
            got = attempt()
        except ValidationError as exc:
            ctx.note(f"{what}: {exc}" + (f" — {exc.detail}" if exc.detail else ""))
        else:
            raise Failed(f"{what} was accepted: page {(got or {}).get('id')} v{page_version(got)}")


def archived(ctx: KbContext) -> None:
    old = ctx.page_id(OLD)
    row = listing(ctx).get(old)
    if row is not None and row.get("status") == "current":
        raise NeedsOperator(f"archive old.md's page by hand (••• → Archive): {ctx.space.page_url(old)}; then re-run")
    if row is not None:
        ctx.note(f"the default v2 page listing holds the archived page, with status {row.get('status')!r}")
    else:
        path = f"{WIKI}/api/v2/spaces/{ctx.space.id}/pages"
        expect(old in {str(p["id"]) for p in ctx.client._walk(path, {"limit": 250, "status": "archived"})},
               f"old.md's page {old} is in neither the listing nor its archived pages: was it deleted?")
        ctx.note("the default v2 page listing leaves archived pages out; `status=archived` lists them")
    title = expected(ctx.run_id)[OLD][0]
    try:
        got = ctx.client.create_page(ctx.space.id, ctx.page_id(ROOT), title, adf.empty())
    except ValidationError as exc:
        ctx.note(f"an archived page's title blocks a new page: {exc}")
    else:
        ctx.ids["stray"] = str(got["id"])
        ctx.note(f"an archived page's title does NOT block a new page: made page {got['id']}, which has no md-source "
                 "(the publisher leaves it alone); archive it by hand")
    before = len(ctx.calls())
    report = ctx.publish(REMOVE)
    expect(report.ok and not acts(report, "orphan") and report.writes == 0 and not writes_since(ctx, before),
           f"orphans {acts(report, 'orphan')}, {report.writes} page writes")
    ctx.note("the publisher no longer reports the archived page, and writes nothing")


CASES: tuple[Case, ...] = (
    Case("space", "read-proven before write: the space, its homepage, a fresh and empty parent", space_check),
    Case("publish", "a dry run writes nothing; the tree lands under the parent, titled and nested, links resolving",
         first_publish),
    Case("search", "a page's own labels hold the shared label at once, and how long CQL lags them; "
                   "a file's own label finds its page", search_lag),
    Case("paging", "_links.next on the v2 listing and v1 CQL, one row at a time: its form, and the walk follows it",
         paging),
    Case("rerun", "the same tree again writes nothing: every page unchanged, none drifted", rerun),
    Case("edit", "one file edited makes exactly one new version of its page, and nothing else", edit),
    Case("move", "a v2 PUT with parentId moves a page; the publisher reports it as drift, and the next edit puts it back",
         move),
    Case("remove", "a removed file's page is reported as an orphan; nothing is written or deleted", remove),
    Case("refusals", "the real bodies of a stale-version PUT and a duplicate-title create", refusals),
    Case("archived", "once a person archives the orphan: the listing, whether its title blocks, the publisher leaves it",
         archived),
    Case("no-delete", "no DELETE request was sent at any point in the run", no_delete, always=True),
)


def make_client(cfg: KnowledgeConfig, *, throttle: float = DEFAULT_THROTTLE
                ) -> tuple[Confluence, Callable[[], list[tuple[str, str]]]]:
    """The client on a real transport, plus that transport's wire log."""
    transport = JiraTransport(cfg.site, lambda: secrets.get(cfg.user_env), lambda: secrets.get(cfg.token_env),
                              throttle=throttle)
    return Confluence(transport), lambda: transport.log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m conformance.knowledge", description=__doc__.split("\n\n")[0])
    parser.add_argument("config", help="the publisher config: a throwaway space, a fresh and empty parent page")
    parser.add_argument("--dry-run", action="store_true", help="list the cases and what the record shows; no calls")
    parser.add_argument("--run-id", help="names this run's label, titles and record (default: today, YYYYMMDD)")
    parser.add_argument("--throttle", type=float, help="seconds between calls (default: the Jira transport's own)")
    parser.add_argument("--reports", type=Path, default=REPORTS, help="where run records go")
    args = parser.parse_args(argv)
    run_id = args.run_id or f"{date.today():%Y%m%d}"
    if not _RUN_ID.match(run_id):
        parser.error("--run-id must be lowercase letters, digits, - or _ (it goes into a label)")

    try:
        cfg = load(args.config)
    except InvalidKnowledgeConfig as exc:
        print("invalid publisher config:\n  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 2
    cfg = replace(cfg, label=f"{cfg.label}-{run_id}")
    record = args.reports / f"{Path(args.config).stem}-{run_id}.json"
    state = runner.load_state(record, run_id)
    print(f"knowledge conformance: space {cfg.space}, parent page {cfg.parent}, label {cfg.label}, run {run_id}\n"
          f"record: {record}")

    if args.dry_run:
        for case in CASES:
            rec = state["cases"].get(case.name)
            mark = f"[{rec['status']} {rec['at']}]" if rec else "[not run]"
            print(f"  {case.name:<11} {mark:<30} {case.summary}")
        return 0

    client, calls = make_client(cfg, **({"throttle": args.throttle} if args.throttle is not None else {}))
    with tempfile.TemporaryDirectory(prefix="kb-conformance-") as work:
        ctx = KbContext(client, cfg, run_id, Path(work), calls)
        verdict = runner.run(CASES, ctx, state, save=lambda s: runner.save_state(record, s))  # type: ignore[arg-type]
    statuses = [c["status"] for c in state["cases"].values()]
    print(f"\nverdict: {verdict.upper()} — " + ", ".join(
        f"{statuses.count(s)} {s}" for s in (runner.PASS, runner.SKIP, runner.FAIL, runner.STOP) if s in statuses))
    return {runner.PASS: 0, runner.FAIL: 1, runner.STOP: 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
