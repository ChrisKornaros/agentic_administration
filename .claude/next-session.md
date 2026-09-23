# Next session — Phase 3 step 4 (written 2026-09-23)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 Phase 3 row, §7 (flow), D5, D12
- **Suggested branch:** `feat/phase3-gate`
- **Phase 3 gate:** a requester-style transcript in Claude Code against Plane produces a correctly placed story with acceptance criteria and the review label.

Phase 3 is one PR per step: ~~(1) `server/` MCP server~~, ~~(2) `schema/` intake schema~~, ~~(3) `skills/` `intake` + `create-story` / `create-bug` / `create-epic`~~ (all done 2026-09-23), **(4) the gate transcript against AGADMIN**.

## Do
1. `/phase-kickoff` for step 4. This is the first live run of the server and skills. It writes to AGADMIN only, so ask permission first, as for conformance.
2. **Load the skills and the server into a Claude Code session.** The route checked on 2026-09-23 against the Claude Code docs is a plugin:
   - `.claude-plugin/plugin.json` (`name`, `description`), the existing `skills/`, and `.mcp.json` running `uv run python -m server boards/agentic_administration.toml`.
   - Start it with `claude --plugin-dir .`.
   - Plugin skills show up as `/<plugin>:intake`, and plugin MCP tools as `mcp__plugin_<plugin>_<server>__<tool>`.
   - The Agent SDK loads plugin skills too, but not a root `skills/` dir on its own.
   - The `.mcp.json` needs the token env. See the live recipe in CLAUDE.md → Project rules.
3. **Run the gate as a requester would:** two sentences in, then `intake` → `create-story` → preview → yes → commit. Check the story on the board: level, parent epic, the acceptance criteria in the description, and `needs-review`. Save the transcript as dated evidence. Board content stays out of git, so commit only a redacted or summarized record.
4. If there's time, also run an epic split, which exercises the one-yes-then-re-ask-on-difference flow.
5. Flip README status, and update roadmap/14's Phase 3 row in the AOR PR below.

## To run / verify
- `uv run pytest`: 206 pass, offline.
- Server: `uv run python -m server boards/<board>.toml` (stdio).

## Open questions / watch-outs
- **Latency:** `find_items(query=…)` fetches each hit with a separate GET at 1.5 s. The skills pass `limit=5`, which is about 16 s worst case. Check how it feels in the transcript.
- **Title case:** "title" capitalizes every word, small words included ("Export Reports As CSV"). The skills say so, and `tests/test_skills.py` checks their examples against it.
- **AOR owes roadmap/14 these, as a separate AOR PR:**
  - (a) the split lives in the schema as `parts`, with a `#<part>` sibling parent;
  - (b) `propose_item` takes the record (`intake=…`, `part=…`), still 11 tools;
  - (c) a split is confirmed once from the record, then committed item by item, re-asking only on a differing preview (warning, `existing`, failure). Chris's call, 2026-09-23;
  - (d) intake id `YYYYMMDD-<slug>`, made once per request, with `-2` added on a first-proposal collision;
  - (e) §8's `context_provider` is one step of the `intake` skill (default `find_items`), not code;
  - also: roadmap/14's status line still says the MCP server is step 1.
- Next full conformance run: a new `--run-id`, ideally in October, to exercise the date-parsing fix end to end.

---
*Written at session end by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
