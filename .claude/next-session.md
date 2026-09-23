# Next session — Phase 3 step 2 (written 2026-09-23)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §7 (intake schema + confirmation flow), §9 Phase 3 row, §8 (`context_provider` seam)
- **Suggested branch:** `feat/phase3-intake-schema`
- **Phase 3 gate:** a requester-style transcript in Claude Code against Plane produces a correctly placed story with acceptance criteria and the review label.

Phase 3 is one PR per step: ~~(1) `server/` MCP server~~ (done 2026-09-23), **(2) `schema/` intake schema + its Markdown rendering**, (3) `skills/` `intake` + `create-story` / `create-bug` / `create-epic`, (4) the gate transcript against AGADMIN.

## Do
1. `/phase-kickoff` for step 2. No new runtime dependency is expected (stdlib dataclasses, like `server/model.py`).
2. The schema's v1 fields, from §7: `problem`, `outcome`, `constraints`, `urgency`, `related`, `acceptance` (Given/When/Then), `proposed_placement` (level, parent, feature, iteration). It also needs a stable record `id`: that becomes `propose_item`'s `intake_id`, and `external_id` = `intake_id[/part]`.
3. Seed it from AOR's [requirement-intake template](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/templates/_shared/requirement-intake.template.md). Its top half generalizes; its Triage half stays in the vault.
4. The Markdown rendering is the `description` that `propose_item` takes, so the acceptance criteria land in the item body.

## To run / verify
- `uv run pytest` (offline). Currently 175 pass.
- Server: `uv run python -m server boards/<board>.toml` (stdio). The live recipe is in CLAUDE.md → Project rules.

## Open questions / watch-outs
- Does decomposition (one intake → an epic plus stories) belong in the schema (a list of parts) or only in the skill (step 3)? `part` already exists on `propose_item`.
- `find_items(query=…)` fetches each hit one by one (up to 2×limit GETs at the throttle). The tool's default limit is 20; watch its latency in step 4.
- At propose, only these are checked against the board: labels, assignees, parent, container features, and the iteration (open). Component modules and collapse labels are resolved when committing, before any write.
- The Claude Code wiring (and how the token env reaches the server) is proven in step 4, not written up yet.
- Next full conformance run: a new `--run-id`, ideally in October, to exercise the date-parsing fix end to end.

---
*Written at session end by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
