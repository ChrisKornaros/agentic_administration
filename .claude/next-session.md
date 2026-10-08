# Next session: Phase 6c step 6, the gate (written 2026-10-08, after step 5's plan-cycle)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row **6c** (gate: a full Food Content cycle planned through the product with only config, nothing written outside it), **D38–D42**, §3.7 (the Food Content run). Phase 7 follows 6c.
- **Deadline: 2026-10-27.** The Jira and Confluence Premium trials end that day. The open items below that need Jira still have to land before then.

## The 6c plan (kickoff 2026-10-05, Chris confirmed)
Six PRs: `probe` ✅ → `board-types` ✅ → `dates-fields` ✅ → `templates` ✅ → `plan-cycle` ✅ → **`gate`**. The kickoff's answers and inferred items are in project memory (`phase6c-decisions`).

## Done: step 5, `feat/phase6c-plan-cycle` (D42's skill)
`skills/plan-cycle/SKILL.md` reads the board and the cycle (`get_iteration`, `find_items(iteration=…, limit=200)`, and the epic by title). It drafts the epic from the epic template, with the cycle's dates and the title from its pattern, and one slot per weekday in each template's `days`, with `dates` saying which date the day sets. The PM edits the list. Next it checks one slot per template, plus each changed slot, with a `propose_item` that has no parent or iteration, and shows the exact write-up of every item, field and call before taking one yes. Then come `create_iteration`, the epic's propose → commit, each slot's propose → commit under the epic in the cycle, and a read-back (`find_items` for membership, `get_item` for the rest). Intake sends a single dated piece on a cadence board to plan-cycle. The framing line names plan-cycle on all three hosts. A new test checks that every skill passes only arguments its tool's MCP schema takes. 380 tests. Offline only, since there's no new wire call.

Inferred, not asked (flag for the AOR catch-up as D42 amendments):
- The ids: `<cycle's first day YYYYMMDD>-cycle`, part `epic` or `<template>-<YYYY-MM-DD>` (`-2`, `-3` for a second slot that day), so a rerun finds what landed.
- A slot with no title gets the template's pattern, else "<Template> For <Weekday>, <Month> <Day>". With no text, it gets the skeleton alone.
- Past days of an active cycle get no slot. An item filed some other way on a slot's day, with the same level and feature, leaves that slot out unless the PM keeps it.
- On Jira, the epic stays out of the sprint (unverified live). On Plane it goes in the cycle, as on Food Content.
- A rerun commits an `existing` item anyway, so commit_item fills in what an interrupted run left unset.
- One-offs go through plan-cycle, not create-story, which is unchanged.

## Next: step 6, the gate, `feat/phase6c-gate`
Hermes `po` on Discord plans Food Content `202611` with only config. Before it, in this order, each with an exact write-up first:
- FCONTENT gets a Bug type (Chris, in Plane's UI). Its config (gitignored `boards/food-content.toml`) switches `bug` back to `type = "Bug"`, drops the review label, sets `board_type = "calendar"`, and gains `[fields]` for its two Story properties plus its templates (an epic template and the post templates with their `days`). Run `describe_board` until it's clean.
- ms01: pull the repo (po loads `skills/` in place) and re-copy `examples/hermes/SOUL.md`, whose framing line changed in this step. Give po the Food Content board, either as a second profile or by switching po's board.
- Then the run, a summary in `transcripts/` (keys and checks, no board content), and the README status.
- Done when 202611's epic and its slots are on FCONTENT through po alone, and the read-back matches the approved write-up.

## After 2026-10-27
- Re-run the read-only Confluence probe on Free (§11).

## Open follow-ups (not blockers)
- **Plane `get_item` by key reports no iteration** (gate finding 6): the by-key read returns `cycle_id: null`. Fix the adapter and the fake. plan-cycle's read-back works around it with `find_items(iteration=…)`.
- **Today comes from the machine's date** (gate finding 7) in both adapters.
- **No Jira sprint is active** until `202611` is started. Chris's call before Oct 27.
- `groom` hasn't run under a host. `AGADM-6` is its first real item, before Oct 27.
- **Food Content for the rest of October** is still unplanned. plan-cycle on `202610` could now cover it, since past days get no slot. It's Chris's call whether that happens before the gate or instead of part of it.
- Plane's `get_item` costs a GET per property on the item's type. That's fine at two properties and worth watching on a board with many. plan-cycle's read-back calls it once per item.
- `publish-docs.yml` has never run in GitHub Actions (private until Phase 7). Plane's renderer has no tables. The Phase 5 items carry over.

---
*Written by the session-handoff module after `feat/phase6c-plan-cycle`. If the roadmap has moved on, trust the roadmap over this file.*
