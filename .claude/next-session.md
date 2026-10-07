# Next session: Phase 6c step 2, board types (written 2026-10-07, after step 1's probe)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row **6c**, D38–D42, §3.7 (the Food Content run), §6 (the planned config keys). Phase 7 follows 6c.
- **Deadline: 2026-10-27.** The Jira and Confluence Premium trials end that day. Step 3's live Jira run has to land before then.

## The 6c kickoff (2026-10-05, Chris confirmed)
Six PRs, one per step: `feat/phase6c-probe` ✅ → `board-types` → `dates-fields` → `templates` → `plan-cycle` → `gate`.
- **D42's confirm, now asked:** `plan-cycle` shows the exact write-up of every item, field and call for the whole cycle, then takes one yes.
- **Date rule:** a weekday cadence. A template names the weekdays it fills, `plan-cycle` generates every slot in the cycle, and the PM can edit the plan before the yes.
- **Gate:** Hermes `po` on Discord plans Food Content's `202611` with only config, and nothing is written outside the 11 tools. Jira's dates and custom fields pass live conformance before 10-27. ms01 needs a Food Content board config (a second profile, or po's board switched).
- **Inferred and flagged at the kickoff** (Chris didn't object):
  - on a calendar board, giving `labels.review` turns review on;
  - Jira finds its Start date field by name;
  - a template can set `state`;
  - the cycle epic's name comes from an epic template's `title` pattern;
  - FCONTENT gets a Bug type before the gate (D39), and its config drops the `bug` label mapping and the review label. Both are real-board writes, shown as an exact write-up first.

## Done: step 1, the read-only probe (`feat/phase6c-probe`)
[probes/README.md](../probes/README.md) has both rows. What they settle for step 3:
- **Plane:** an option property's options ride on its record, so option *names* resolve to ids at `describe_board`, the same way labels do. A value reads one property per GET, and an unset value answers 404, which means unset. No read returns all of an item's values at once, so `get_item` reads them and the list doesn't. Dates are `start_date` / `target_date` on every item read. The throwaway project has no properties, so conformance must provision one.
- **Jira:** the target date is `duedate`, and the start date is the field named "Start date" (`customfield_10015` on this site). Both are on every create and edit screen. **No other custom field is on AGADM's screens.** The live pass-through needs one added first, either as an operator step in conformance or by Chris in the UI. Settle that at step 3's start.

## Next: step 2, `feat/phase6c-board-types` (D38–D40)
- `board_type = "software" | "calendar"` (software is the default). On a calendar board, `levels.bug` may be left out, and the review label is on only when `labels.review` is given. A software board still requires both.
- Service: add the review label only when it's on. A bug proposed on a board without a Bug level refuses with a clear message. `describe_board` reports `board_type`, with `review_label` null when review is off.
- Both adapters' config checks skip what's off. Wording in `create-bug`, `groom`, and the "marked for review" lines in `create-story`, `create-epic` and `intake`.
- `examples/boards/calendar.example.toml`, tied by tests. Done when `uv run pytest` is green above the baseline of 330, and the calendar example loads and checks.

## After 2026-10-27
- Re-run the read-only Confluence probe on Free (§11).

## Open follow-ups (not blockers)
- **Plane `get_item` by key reports no iteration** (gate finding 6, confirmed by the 6c probe on 6/6 stories): the workspace by-key read returns `cycle_id: null`; the by-id read and the list carry it. Fix the adapter and the fake transport.
- **Today comes from the machine's date** (gate finding 7) in both adapters, though iteration dates are read in the board's time zone.
- **No Jira sprint is active** until `202611` is started. Chris's call before Oct 27: start it early, or let it go.
- `groom` hasn't run under a host. `AGADM-6` (Backlog, `needs-review`) is its first real item, before Oct 27.
- **Food Content for the rest of October** is still unplanned. 6c's gate plans `202611`.
- `publish-docs.yml` has never run in GitHub Actions (private until Phase 7). Plane's renderer has no tables. The Phase 5 items carry over.

---
*Written by the session-handoff module after `feat/phase6c-probe`. If the roadmap has moved on, trust the roadmap over this file.*
