# Next session: Phase 6c step 4, templates (written 2026-10-08, after step 3's dates and fields)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row **6c**, **D41** (templates), **D42** (`propose_item(template=…)`), §3.7 (the Food Content run), §6 (`templates`). Phase 7 follows 6c.
- **Deadline: 2026-10-27.** The Jira and Confluence Premium trials end that day. Step 3's live Jira run is done; the open items below that need Jira still have to land before then.

## The 6c plan (kickoff 2026-10-05, Chris confirmed)
Six PRs: `probe` ✅ → `board-types` ✅ → `dates-fields` ✅ → **`templates`** → `plan-cycle` → `gate`. The kickoff's answers and inferred items are in project memory (`phase6c-decisions`).

## Done: step 3, `feat/phase6c-dates-fields` (D41's data half)
`WorkItem` has `start_date`, `target_date` and `fields` (keyed by the config's `[fields]` names). `describe_board` lists each field with its kind, options and the levels that carry it. `propose_item` / `update_item` take dates and fields, and `propose_item` checks values against the board. Plane: dates in the POST / PATCH; values by the `…/values/` upsert after the item exists, read one GET per property by `get_item` only. Jira: `duedate` and "Start date" (by name), values in the create / PUT, options as `{"value": …}`. Live conformance passed on both (10 pass, 2 skip each; [conformance/README.md](../conformance/README.md#results)). Chris added the test fields in the UIs; the suite never creates one. 361 tests.

Inferred, not asked (flag for the AOR catch-up as D41 amendments): option values are names; `update_item` takes dates and fields; a value can't be cleared; Jira's start date is found by name; a retried commit fills in unset values.

## Next: step 4, `feat/phase6c-templates` (D41's template half + D42's argument)
- Story templates in the board config: each names a module, labels, custom-field values (by `[fields]` name), a date rule and a description skeleton (on Food Content, the caption with its hashtags), and may set `state` (inferred at the kickoff).
- **Date rule = weekday cadence** (kickoff): a template names the weekdays it fills (`days = [...]`), and `dates = "target"` (or similar) says which date the slot's day fills. `plan-cycle` (step 5) generates the slots; this step only carries the rule in the config.
- `propose_item(template=…)` fills the item from the template, and the request adds the date and the specifics. The server stays at 11 tools (D13). It reuses propose → commit and the `external_id` key.
- The cycle epic's name comes from an epic template's `title` pattern (kickoff, inferred), e.g. `<Month> <Year> Content`.
- No new vendor surface, so likely offline-proven only. Settle at the start whether a live check is worth it. Done when `uv run pytest` passes above 361 and the calendar example carries a template that loads.

## After 2026-10-27
- Re-run the read-only Confluence probe on Free (§11).

## Open follow-ups (not blockers)
- **Plane `get_item` by key reports no iteration** (gate finding 6): the by-key read returns `cycle_id: null`. Fix the adapter and the fake.
- **Today comes from the machine's date** (gate finding 7) in both adapters.
- **No Jira sprint is active** until `202611` is started. Chris's call before Oct 27.
- `groom` hasn't run under a host. `AGADM-6` is its first real item, before Oct 27.
- **Food Content for the rest of October** is still unplanned. 6c's gate plans `202611`. Before the gate, FCONTENT gets a Bug type and its config drops the `bug` label mapping and the review label, and gains `[fields]` for its two Story properties (exact write-up first).
- Plane's `get_item` costs a GET per property on the item's type; fine at two properties, worth watching on a board with many.
- `publish-docs.yml` has never run in GitHub Actions (private until Phase 7). Plane's renderer has no tables. The Phase 5 items carry over.

---
*Written by the session-handoff module after `feat/phase6c-dates-fields`. If the roadmap has moved on, trust the roadmap over this file.*
