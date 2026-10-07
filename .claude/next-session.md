# Next session: Phase 6c step 3, dates and fields (written 2026-10-07, after step 2's board types)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row **6c**, **D41**, §3.7 (the Food Content run), §6 (`fields`). Phase 7 follows 6c.
- **Deadline: 2026-10-27.** The Jira and Confluence Premium trials end that day. This step's live Jira run has to land before then.

## The 6c plan (kickoff 2026-10-05, Chris confirmed)
Six PRs: `probe` ✅ → `board-types` ✅ → **`dates-fields`** → `templates` → `plan-cycle` → `gate`. The kickoff's answers and inferred items are in project memory (`phase6c-decisions`).

## Done: step 2, `feat/phase6c-board-types` (D38–D40)
`board_type = "software" | "calendar"` in the config. On a calendar board, `bug` may be left out (capabilities report `absent`, and `propose_item` refuses a bug before any read), and review is on only when `labels.review` is given. `describe_board` reports `board_type`, with `review_label` null when review is off. [examples/boards/calendar.example.toml](../examples/boards/calendar.example.toml). Conformance refuses a calendar config, since its cases file a bug. 343 tests.

## Next: step 3, `feat/phase6c-dates-fields` (D41's data half)
- `WorkItem` gains start and target dates and a custom-field pass-through. The config's `fields` maps a field name to the tracker's property (a Plane work-item property, a Jira `customfield_*`), and the adapter writes the value as given.
- What the probe settled ([probes/README.md](../probes/README.md)):
  - **Plane:** option *names* resolve to ids at `describe_board`, as labels do. A value reads one property per GET, and an unset value answers 404. `get_item` reads the values, and the list doesn't. Dates are `start_date` / `target_date`. The write is `POST …/work-item-properties/{id}/values/ {"value": …}`, an upsert (§3.7). The throwaway project has no properties, so conformance provisions one.
  - **Jira:** the target date is `duedate`, and the start date is the field named "Start date", found by name. **No other custom field is on AGADM's screens:** settle at the start whether conformance adds one as an operator step or Chris adds it in the UI.
- Live conformance on AGADMIN and AGADM (asks permission). Done when `uv run pytest` passes above 343 and both conformance runs pass the new date and field cases.

## After 2026-10-27
- Re-run the read-only Confluence probe on Free (§11).

## Open follow-ups (not blockers)
- **Plane `get_item` by key reports no iteration** (gate finding 6): the by-key read returns `cycle_id: null`. Fix the adapter and the fake.
- **Today comes from the machine's date** (gate finding 7) in both adapters.
- **No Jira sprint is active** until `202611` is started. Chris's call before Oct 27.
- `groom` hasn't run under a host. `AGADM-6` is its first real item, before Oct 27.
- **Food Content for the rest of October** is still unplanned. 6c's gate plans `202611`. Before the gate, FCONTENT gets a Bug type and its config drops the `bug` label mapping and the review label (exact write-up first).
- `publish-docs.yml` has never run in GitHub Actions (private until Phase 7). Plane's renderer has no tables. The Phase 5 items carry over.

---
*Written by the session-handoff module after `feat/phase6c-board-types`. If the roadmap has moved on, trust the roadmap over this file.*
