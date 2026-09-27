# Next session: Phase 5 step 2, the Jira adapter (written 2026-09-27)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 Phase 5 row, D2, §4 (the Jira column)
- **Branch (here):** `feat/phase5-jira-adapter`, then `feat/phase5-jira-conformance` (the gate)
- **Phase 5 gate:** conformance passes against a personal Jira Cloud site, never a company site.
- **Deadline:** the site's Premium trial ends **2026-10-27**. Phase 6's rollover gate needs Jira too, and sprints keep working on Free.

Step 1 is done: the preflight and the read-only probe (`feat/phase5-jira-probe`). Its evidence row is in [probes/README.md](../probes/README.md), and the full report is the gitignored `probes/jira-probe-report.json`.

## The target
- Chris's personal site (its URL is in project memory, `jira-site`), a **company-managed** Scrum project "Jira Test", key **`AGADM`** (id 10001). Its board is "AGADM board", **id 2**, and it has an empty future sprint, "AGADM Sprint 1" (id 3).
- An earlier team-managed project `AGADMIN` still exists on the site. It is not the target.
- Auth is Basic: the account email plus a classic API token, against the site URL. Both come from Bitwarden item `agentic_administration:jira:api` (the token in its password, the email in its username):
  `JIRA_API_TOKEN_BW_ITEM=… JIRA_USER_BW_ITEM=… JIRA_USER_BW_FIELD=username BW_SESSION="$(cat ~/.cache/bw_session)"`. Run `bw sync` first if the item changed.

## Decided 2026-09-27 (Chris), to build to
1. **Feature** collapses to a label, `feature:<name>` with spaces turned into dashes. Premium custom levels sit only *above* Epic, so roadmap/14 §4's "Feature = custom hierarchy level" is wrong for Jira. That's an AOR fix.
2. **Initiative** collapses to a description line, as on Plane. Phase 5 uses no Premium-only feature.
3. **Idempotency** is a visible `xid:<external_id>` label, set in the create call and found with JQL `labels = "…"`, the only exact text match JQL has.
   - The adapter keeps it whenever labels are replaced, as when the review label is cleared.
   - `/search/jql` is eventually consistent, so the adapter also remembers the items it has created and re-checks them with `reconcileIssues`.
4. **States map by name:** `Backlog` / `To Do` / `In Progress` / `Cancelled` / `Done`. Every transition is global and named after its target status. Chris is moving To Do into the To Do category and Cancelled into Done.
5. **Sprints: dates decide.** `create_iteration` starts a sprint (PUT `state: active`) when its dates cover today. It fails cleanly if another sprint is already active, since there are no parallel sprints. Close = `state: closed`.

## Step 2: build
- Package `adapters/jira/`:
  - `transport.py`: Basic auth; map 429 + `Retry-After` to `RateLimited`; never retry a 401 (the CAPTCHA risk).
  - `adf.py`: Markdown ↔ ADF.
  - `adapter.py` and `__main__.py describe`.
- `server/config.py`: the Jira connection is `site`, `project_key`, `board_id`, plus the account email's env var.
- Also: `server/__main__.py` dispatch, `examples/boards/jira.example.toml`, and offline tests on a `tests/fake_jira.py` transport.
- Wire facts from the probe:
  - Search is `/rest/api/3/search/jql` (the old `/search` returns 410); always pass `fields`.
  - Parent is set with the `parent` field.
  - The Sprint field is `customfield_10020`, which is on the create screen.
  - Labels are free-form: `describe_board` shouldn't demand they exist. They can't contain spaces.
- **Done when** `uv run pytest` is green with the new tests, and `uv run python -m adapters.jira describe boards/jira-agadm.toml` prints `config fits the board.` That's a live read with no writes.

## To run / verify
- `uv run pytest`: 209 pass, offline.
- `uv run python probes/jira_phase5_readonly.py --plan` needs no network. The live run takes the env above plus `JIRA_SITE` and `JIRA_PROJECT=AGADM`.

## Owed to AOR after Phase 5 (one catch-up session)
- The roadmap/14 §4 Jira column: Feature and Initiative collapse, and custom levels sit only above Epic.
- A §3.5 findings section from the probe and conformance, and D-numbers for the five calls above.
- Phase 5 ✅.

## Open follow-ups (not Phase 5 blockers)
- **Parent key:** Plane's `get_item`, `find_items` and `commit_item` return the parent as a bare id. `expand=parent` gives its `sequence_id` (a small adapter PR).
- **Split repetition:** every story in a split repeats the whole request. This is Chris's call, and the rendering is in `schema/intake.py`.
- **`related` as a link:** it's still a description line. A relation write needs a conformance case first.
- **No comment read:** the server can add a comment but can't read one back.
- **After Phase 5:** Chris has an Atlassian-tooling project to build and test. It waits until the core Jira workflow is done.

---
*Written at the end of Phase 5 step 1 by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
