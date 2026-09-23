# Next session — Phase 3 step 3 (written 2026-09-23)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §5 layer 3 (skills), §7 (intake + confirmation flow), §8 (`context_provider` seam), §9 Phase 3 row
- **Suggested branch:** `feat/phase3-skills`
- **Phase 3 gate:** a requester-style transcript in Claude Code against Plane produces a correctly placed story with acceptance criteria and the review label.

Phase 3 is one PR per step: ~~(1) `server/` MCP server~~ (done 2026-09-23), ~~(2) `schema/` intake schema + Markdown rendering~~ (done 2026-09-23), **(3) `skills/` `intake` + `create-story` / `create-bug` / `create-epic`**, (4) the gate transcript against AGADMIN.

## Do
1. `/phase-kickoff` for step 3. These are the product's skills in `skills/` (public), not the dev skills in `.claude/skills/`.
2. `intake`: the conversation that fills a `schema.intake.Intake` record from two sentences. It asks for problem and outcome first, then drafts the Given/When/Then criteria for the requester to confirm. Before proposing placement it calls the §8 `context_provider` hook (default: `find_items`), which fills `related` and informs `placement`.
3. `create-story` / `create-bug` / `create-epic`: decomposition and placement over the record's `parts`. A split names every part, and stories take `placement.parent = "#epic"`. Commit the epic first, because `#epic` resolves by external_id only once it exists.
4. The confirm (D12) belongs to the skill: show the preview, wait for a yes, then `commit_item`. With `confirm = "never"`, commit without pausing.

## To run / verify
- `uv run pytest` (offline). Currently 190 pass.
- Server: `uv run python -m server boards/<board>.toml` (stdio). The live recipe is in CLAUDE.md → Project rules.

## Open questions / watch-outs
- **Confirming a split:** story previews can't exist before the epic is committed (`#epic` resolves by lookup). So is it one yes for the split shown from the record, then per-item previews, or a yes per item? D12 says the requester sees what lands.
- **Intake id convention:** the skill mints the id once and reuses it on every retry. `YYYYMMDD-<slug>` fits the schema's `[A-Za-z0-9._-]{1,64}`. Settle it in the skill.
- **Skill format and loading:** the SKILL.md format should load in both Claude Code and the Agent SDK. How Claude Code picks up `skills/` for step 4 (a plugin, or a link into `.claude/skills/`) is still open.
- **AOR owes roadmap/14 two decisions from this step,** a separate AOR PR: (a) the split lives in the schema as `parts`, with a `#<part>` sibling parent; (b) `propose_item` takes the record (`intake=…`, `part=…`) and renders the description, keeping 11 tools.
- `find_items(query=…)` fetches each hit one by one (up to 2×limit GETs at the throttle). Watch its latency in step 4.
- At propose, only these are checked against the board: labels, assignees, parent, container features, and the iteration (open). Component modules and collapse labels are resolved when committing, before any write.
- Next full conformance run: a new `--run-id`, ideally in October, to exercise the date-parsing fix end to end.

---
*Written at session end by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
