# Next session: Phase 6b step 3 `conformance`, or the Phase 6 gate from Oct 2 (written 2026-09-28)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 rows **6** and **6b**, D26–D29, and §11 (Confluence on Free).
- **6b PRs (`feat/phase6b-<slug>`):** `probe` ✅ → `publish` ✅ (this PR) → **`conformance`** → `read`.
- **Phase 6 PRs:** 1–4 ✅ → **`gate`**, which can run on or after **Oct 2**.
- **Hard deadline: 2026-10-27.** The Jira *and* Confluence Premium trials both end that day. The gate, 6b `conformance` and 6b `read` are all live runs, so they all land before then.

## 6b step 3: `conformance` (can start now; live writes to `AGKB`, so ask Chris first)
- The gate (§9 6b): publish a docs tree to `AGKB` under a fresh parent page (never the homepage, id 393328). A re-run writes 0 pages, links resolve, one edit makes exactly one new version, and a removed file is reported with nothing deleted.
- Credentials: the Jira pair (`JIRA_API_TOKEN_BW_ITEM` + `JIRA_USER_BW_ITEM`, `JIRA_USER_BW_FIELD=username`); config from `examples/knowledge/confluence.example.toml` into `boards/`.
- **Unproven live, check each** (the fake follows the docs on these):
  - the `_links.next` forms (v2 under `/wiki`, v1 relative to it);
  - whether a property PUT bumps the page version (if it does, every page reports drift);
  - whether the v2 page listing includes archived pages, and whether archived titles block new ones;
  - whether a v2 PUT with `parentId` moves a page;
  - how long CQL lags a label write (the subtree scan covers it);
  - the real 409/400 bodies.
- Also in this step: a GitHub Actions example that publishes on push (roadmap row), and a dated results section in [conformance/README.md](../conformance/README.md).

## The Phase 6 gate (from Oct 2)
- Roll `202610` → `202611` with `plan-sprint` through `examples/agent-sdk/chat.py`, on Plane `AGADMIN` and Jira `AGADM`.
- **Chris first:** a metered Anthropic API key in Bitwarden, via `ANTHROPIC_API_KEY_BW_ITEM`, with its id saved to memory.
- Afterwards: `transcripts/<date>-phase6-gate.md`, the README status line, then the Phase 6 AOR catch-up (D30 and up).

## After 2026-10-27
- Re-run the read-only Confluence probe, and a Jira read, on Free. That answers roadmap/14 §11's two edition questions. §11 says the probe answered the Confluence one, but it ran on Premium: fix that wording at 6b's AOR catch-up.

## Open follow-ups (not blockers)
- 6b's AOR catch-up: the probe findings go into §3; add the publish calls (identity by the `md-source` property plus a subtree scan, titles with a folder suffix, links drop their `#fragment`, images unpublished).
- The Plane Markdown renderer has no tables yet (ADF does now).
- The README Claude Code command change is proven offline only. Carried over: the Phase 5 items.

---
*Written at the end of Phase 6b step 2 by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
