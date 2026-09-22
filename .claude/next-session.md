# Next session — Phase 2, step 4: the conformance suite, run live

Source: agentic_optimization_research `roadmap/14-agentic-administration.md`
§9 Phase 2 row ("the conformance suite run against a throwaway Plane
project. First conformance cases: `external_id` write + search round-trip;
Bug-type provisioning; whether `PATCH …/features` flips `epics`"), §3.1
findings, §6 (config validated live before any write), D7 (a new backend =
adapter + conformance suite). Steps 1–3 are merged (`server/model.py`,
`server/config.py`, `adapters/base.py` + `adapters/plane/`); trust the
roadmap over this note if they disagree. The step-4 gate: **adapter passes
conformance live**, which closes Phase 2.

**Branch:** `feat/phase2-conformance`

## What step 3's live read found (2026-09-22, read-only)

`uv run python -m adapters.plane describe boards/agentic_administration.toml`
against the throwaway project (identifier **`AGADMIN`**, resolved from the
name; the note that guessed `AA` was wrong) answered cleanly through
Bitwarden + Cloudflare and refused the config, correctly:

- `types: []` and project features `work_item_types: false`, `epics: false`
  — a **fresh** project has Work Item Types off (the Phase 1 boards all had
  Epic/Story/Task because the feature had been enabled on them).
- No labels, no modules, no cycles; `modules: true`, `cycles: true` are on.
- The default workflow states exist and map 1:1 by name (Backlog, Todo,
  In Progress, Done, Cancelled); `members-lite` and `labels/` answer.

So provisioning is the first conformance case, not a side step.

## Build

1. **`conformance/`** — a pytest-style runner that is *not* under `tests/`
   (never in the default `uv run pytest`; e.g. `uv run python -m conformance
   boards/<board>.toml`, with `--dry-run` listing cases without a call).
   Cases in dependency order, each one idempotent (skip-by-name / by
   `external_id`) so a Cloudflare wall or a 429 mid-run is a safe re-run:
   1. **Provision** (Plane-specific, `PlaneAdapter` extras): try
      `PATCH …/projects/{pid}/features` with `{"work_item_types": true,
      "epics": true}` — **unverified**; if it works, record it; if not,
      stop and ask Chris to flip Work Item Types + Epics in the UI (Project
      Settings → Features), then re-run. Then `provision_work_item_type`
      for Story / Task / Bug (POST `work-item-types`, proven for non-epic
      types in the seed CLI), and labels `needs-review`, `bug`, `feature`,
      `chore`, `docs` via `POST …/labels/` (**unverified write** — add a
      `provision_label` next to `provision_work_item_type`).
   2. `describe_board` → `problems == ()` (the gate flips clean).
   3. `create_item` epic; `find_items(external_id=…)` → the **external_id
      round-trip** (create with `external_id`, search finds exactly it).
   4. Story under the epic, in a module (`create_item(Level.FEATURE)` first),
      with `needs-review`; Bug under the epic; Task under the story.
   5. Hierarchy: a Task parented under the Epic — expect Plane to accept
      (Hierarchy is off) and record it; the mapped `ValidationError` path is
      what the suite asserts if the workspace ever turns Hierarchy on.
   6. `update_item` clearing the review label; `add_comment`.
   7. `create_iteration("202610")`, `move_to_iteration`, and `close_iteration`
      on a cycle that started **before today** (Plane completes a cycle only
      once `end_date` has passed; the adapter pulls it to yesterday and
      re-reads — verify the boundary and fix `close_iteration` if Plane
      counts the end day differently).
   8. Nothing deleted: the suite asserts no `DELETE` was ever sent
      (`PlaneTransport` has no such path; assert on the call log).
2. Keep total POST volume small (Cloudflare's managed challenge showed up
   after ~24 creates in a burst); the throttle stays at 1.5 s.
3. Record outcomes in `conformance/README.md` (dated, like `probes/`) and
   the unverified-write answers go back to AOR `tools/plane/API.md` +
   `roadmap/14 §3.1` as a separate AOR PR (D10: the CLI becomes the seed).

## Secret handoff that works

Chris writes the session key to `~/.cache/bw_session`
(`umask 077; bw unlock --raw > ~/.cache/bw_session`). Run live commands with
the sibling AOR checkout's non-secret `.env` exported and
`PLANE_API_KEY_BW_ITEM="$PLANE_BW_ITEM" PLANE_API_KEY_BW_FIELD="$PLANE_BW_FIELD"
BW_SESSION="$(cat ~/.cache/bw_session)"`; never print any of them. The real
board config is `boards/agentic_administration.toml` (gitignored; types by
name, project by name).

## Open questions to settle in the PR

- Does `PATCH …/features` flip `work_item_types` / `epics`? (API.md says the
  Epics enable is UI-only; the SDK has the PATCH.)
- Does `POST …/labels/` exist on the v1 API as the SDK suggests?
- Which end-day boundary completes a cycle (`end_date < today` or `<=`)?
- Is the `needs-review` label the adapter's job on create, or the MCP
  server's (Phase 3)? Step 3 kept the adapter mechanical; decide before
  the server lands.
