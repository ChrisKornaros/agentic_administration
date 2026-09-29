# Next session: Phase 6b step 4 `read`, or the Phase 6 gate from Oct 2 (written 2026-09-28)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 rows **6** and **6b**, D26–D29 (D27 = the read side), §11 (Confluence on Free).
- **6b PRs (`feat/phase6b-<slug>`):** `probe` ✅ → `publish` ✅ → `conformance` ✅ (this PR, PASS 11/11 live on `AGKB`) → **`read`**.
- **Phase 6 PRs:** 1–4 ✅ → **`gate`**, which can run on or after **Oct 2**.
- **Hard deadline: 2026-10-27.** The Jira *and* Confluence Premium trials both end that day. The gate and 6b `read` are live runs, so both land before then.

## 6b step 4: `read` (can start now)
- The gate (§9 6b): an agent answers from the docs through `search_docs`.
- Build `search_docs` / `get_doc` on a separate `knowledge` MCP server (D27), not on the 11-tool board server. Wire it into `intake`'s context step.
- Already there: `Confluence.page()` (the body as ADF) and `adf.to_markdown`. The probe showed that CQL `text ~` and `siteSearch ~` both answer, and that hits carry `title`, `url`, `excerpt` and `breadcrumbs`.
- **Open (ask, or infer and flag):**
  - Is search scoped to the publisher's label or to the whole space?
  - Does it reuse the publisher TOML, or get its own server config?
  - How does the plugin, and do Hermes and the SDK example, carry a second server? (Consistency by default: each host gets the same ties and tests.)
- The live proof is a requester session answering from the conformance tree already on `AGKB`: `Conformance 20260928` under `Conformance Test`.

## The Phase 6 gate (from Oct 2)
- Roll `202610` → `202611` with `plan-sprint` through `examples/agent-sdk/chat.py`, on Plane `AGADMIN` and Jira `AGADM`.
- **Chris first:** a metered Anthropic API key in Bitwarden, via `ANTHROPIC_API_KEY_BW_ITEM`, with its id saved to memory.
- Afterwards: `transcripts/<date>-phase6-gate.md`, the README status line, then the Phase 6 AOR catch-up (D30 and up).

## 6b's AOR catch-up (after `read`)
- §3: the probe findings, plus the settled list in [conformance/README.md](../conformance/README.md#what-the-2026-09-28-run-settled). Among them: page ids are not in creation order, archived titles still block, and a PUT with `parentId` moves a page.
- The publish calls: identity by `md-source` plus a subtree scan, titles with a folder suffix, links drop their `#fragment`, images unpublished.
- §11 says the probe answered the Confluence Free question, but the probe ran on Premium. Fix that wording.

## After 2026-10-27
- Re-run the read-only Confluence probe, and a Jira read, on Free. That answers §11's two edition questions.

## Open follow-ups (not blockers)
- `examples/knowledge/publish-docs.yml` is checked offline only: the real CLI takes its command, and the install form works from a local path. It hasn't run in GitHub Actions. The repo is private until Phase 7.
- The Plane Markdown renderer has no tables yet. Carried over: the Phase 5 items.

---
*Written at the end of Phase 6b step 3 by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
