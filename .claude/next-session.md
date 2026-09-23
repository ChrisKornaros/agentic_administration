# Next session — 2026-09-23

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 Phase 3 row, §5 layer 3, §7, D5, §11
- **Suggested branch:** `feat/phase3-mcp-server`
- **Phase 3 gate:** a requester-style transcript in Claude Code against Plane produces a correctly placed story with acceptance criteria and the review label.

Phase 3 is one PR per step: (1) `server/` MCP server, (2) `schema/` intake schema + its Markdown rendering, (3) `skills/` `intake` + `create-story` / `create-bug` / `create-epic`, (4) the gate transcript against AGADMIN. This session is step 1.

## Do
1. `/phase-kickoff` for step 1, then `/substrate-preflight` on the official `mcp` Python SDK (the first runtime dependency; its reason goes in the PR).
2. Build the server over `adapters.base.Adapter`, from a board config. Tools: `describe_board`, `find_items`, `get_item`, `get_iteration`, `propose_item`, `commit_item`, `update_item`, `add_comment`, `create_iteration`, `move_to_iteration`, `close_iteration`. No delete, by construction.
3. Server behavior, settled 2026-09-23 (project memory `phase3-decisions`):
   - **Confirm = propose → commit.** `propose_item` validates against the board, adds `labels.review` and an `external_id` derived from the intake record id, renders the description, stores the draft, and returns a short-lived token + preview. `commit_item(token)` writes exactly that draft. Creates only; `confirm = "never"` means the skill commits without pausing.
   - **Title case:** when `naming.item_case` is set and the title doesn't match, propose returns a warning and a suggested title (a conservative title-caser that leaves acronyms, mixed-case words and code names alone). No hard reject.
   - **Errors:** map `AdapterError` subclasses to tool errors the agent can act on (`ConfigMismatch` → fix the board config; `RateLimited` / `Blocked` → wait, then retry).
   - A retried commit finds the existing item by `external_id` instead of duplicating it.

## To run / verify
- `uv run pytest` (offline; server tests run against `tests/fake_plane.py`).
- Live: the secrets recipe in CLAUDE.md → Project rules; board config `boards/agentic_administration.toml` (AGADMIN).

## Open questions / watch-outs
- Drafts live in memory per server process (a restart means proposing again); the token lifetime is not decided yet.
- Rollover (`close_iteration` + moving what's left) is composed above the adapter. It's Phase 6 work, but the tool lands now.
- Next full conformance run: a new `--run-id`, ideally in October, to exercise the date-parsing fix end to end.
- The tool count is now 11 against roadmap §5's "roughly eight". Recording that is for Chris's separate AOR session.

---
*Generated at session-end by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
