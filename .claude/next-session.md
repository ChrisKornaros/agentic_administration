# Next session: Phase 5 step 3, Jira conformance, the gate (written 2026-09-27)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 Phase 5 row, D2, §8 (the conformance suite)
- **Branch (here):** `feat/phase5-jira-conformance`
- **Phase 5 gate:** conformance passes against a personal Jira Cloud site, never a company site.
- **Deadline:** the site's Premium trial ends **2026-10-27**.

Steps 1–2 are done:
- **The probe:** `feat/phase5-jira-probe`, PR #14.
- **The adapter:** `feat/phase5-jira-adapter`, which adds [adapters/jira/](../adapters/jira/) and its offline tests.
- **Live check:** `uv run python -m adapters.jira describe boards/jira-agadm.toml` printed `config fits the board.` against `AGADM` (a read, with no writes).
- The five design calls from 2026-09-27 are built in. They're listed in the module docstring of [adapters/jira/adapter.py](../adapters/jira/adapter.py).

## The target
- Chris's personal site (its URL is in project memory, `jira-site`, and in the gitignored `boards/jira-agadm.toml`).
- A company-managed Scrum project, key **`AGADM`**, board **2**, with an empty future sprint "AGADM Sprint 1".
- Credentials: `JIRA_API_TOKEN_BW_ITEM` and `JIRA_USER_BW_ITEM` both name the Jira item, plus `JIRA_USER_BW_FIELD=username`, plus `BW_SESSION="$(cat ~/.cache/bw_session)"`. Run `bw sync` if the item changed.
- **Ask Chris first:** To Do and Cancelled still read as the `indeterminate` category (as of 2026-09-27). He planned to move To Do into the To Do category and Cancelled into Done. It doesn't matter for the adapter, which maps by name, but it does for Jira's sprint close and reports.

## Step 3: build, then the live run (ask before running it)
- `conformance/jira.py`: `make_adapter` (a `JiraTransport` through `server/secrets.py`) and `provision`.
  - Jira has nothing for the API to provision: labels are free-form, and the types and statuses are UI steps.
  - So `provision` checks `describe_board` and stops with `NeedsOperator` naming whatever is missing.
- `conformance/runner.py` and `__main__.py`: register Jira. `--throttle` defaults to Plane's 1.5 s, so give each backend its own default. Jira's is `adapters.jira.transport.DEFAULT_THROTTLE`, 0.5 s.
- **The generic cases assume Plane in four places. Adapt them per capability, not per backend name:**
  - **`placement`** creates a Feature. On Jira, Feature collapses, so `create_item(FEATURE)` raises `Unsupported`. Use a feature ref by name, and expect the `feature:<name>` label on the story.
  - **`iterations`**: this month's sprint must read active on create (dates decide). Only one sprint can be active on the board.
    - Moving the sub-task (the canonical Task) into a sprint is **unproven**. Jira may refuse it, or carry it with its parent. Record what happens.
  - **`hierarchy`**: expect Jira to refuse a sub-task under an epic (`ValidationError`). Either answer is conformant.
  - **`update`**: `labels=()` must keep the `xid:` label, and a state change is a transition.
- **Done when** `uv run python -m conformance boards/jira-agadm.toml` shows `verdict: PASS` with 0 DELETEs, and [conformance/README.md](../conformance/README.md) has the dated Jira result.

## To run / verify
- `uv run pytest`: 254 pass, offline.
- `uv run python -m adapters.jira describe boards/jira-agadm.toml`: a live read.

## Owed to AOR after Phase 5 (one catch-up session)
- The roadmap/14 §4 Jira column: Feature and Initiative collapse, and custom levels sit only above Epic.
- A §3.5 section with the findings from the probe, the adapter and conformance, and D-numbers for the five calls.
- Phase 5 ✅.

## Open follow-ups (not Phase 5 blockers)
- **Parent key:** Plane's reads return the parent as a bare id (a small PR using `expand=parent`). Jira's reads already carry the parent's key and level.
- **Split repetition:** every story in a split repeats the whole request. This is Chris's call; the rendering is in `schema/intake.py`.
- **`related` as a link:** it's still a description line. A relation write needs a conformance case first.
- **No comment read:** the server can add a comment but can't read one back.
- **After Phase 5:** Chris has an Atlassian-tooling project to build and test. It waits until the core Jira workflow is done.

---
*Written at the end of Phase 5 step 2 by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
