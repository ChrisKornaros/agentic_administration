# Next session — Phase 4, Hermes wiring (written 2026-09-24)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 Phase 4 row, D8, §11 (the ssh question)
- **Suggested branch:** `feat/phase4-hermes`
- **Phase 4 gate:** the same requester transcript from Discord through Hermes on ms01 gives the same result, with no step dropped.

Phase 3 is done (2026-09-24). It passed its gate: [transcripts/2026-09-24-phase3-gate.md](../transcripts/2026-09-24-phase3-gate.md) records AGADMIN-10, a story under epic AGADMIN-6, in Backlog with `needs-review` and three Given/When/Then criteria.

## Do
1. **AOR first, as a separate AOR session and PR, not from here.** roadmap/14 needs:
   - the Phase 3 row ✅ 2026-09-24, with a link to the gate record;
   - a status line that says Phase 4 is next;
   - the owed items: (a) a split lives in the schema as `parts`, with a `#<part>` sibling parent; (b) `propose_item` takes the record (`intake=…`, `part=…`), still 11 tools; (c) a split is confirmed once, then committed item by item, re-asking only when a preview differs; (d) the intake id is `YYYYMMDD-<slug>`, with `-2` added on a first-proposal collision; (e) §8's `context_provider` is the one retrieval step in `intake`, not code;
   - plus the gate's finding that the host must frame the agent as a backlog assistant, or Claude Code reads a request as a build task.
2. `/phase-kickoff` for Phase 4. Settle §11's ssh question up front: `stay-in-project-tree` denies `ssh`/`scp`/`rsync`. Either Chris runs the ms01 steps himself, or MODULES.md records an exception.
3. **Hermes config (D8):**
   - a global `mcp_servers` entry, stdio, running `uv run --directory <repo> python -m server <board.toml>`;
   - the token through `env`;
   - `tools.include` set to the 11 tools;
   - the framing line from the README's Claude Code section in the Hermes persona or system prompt;
   - the skills loaded in whatever way Hermes loads skills. Check its docs first.
4. Run the story gate from Discord, with Chris as the requester. Record it next to the Phase 3 record, and compare the steps with run 2.

## To run / verify
- `uv run pytest`: 206 pass, offline. `claude plugin validate .` passes, with one expected warning about the root CLAUDE.md.
- The Claude Code requester block is in README → "To try it in Claude Code". Run it from an empty directory.

## Open questions / follow-ups (from the gate, not Phase 4 blockers)
- **Split repetition:** every story in a split repeats the request's whole problem and outcome. Keep items self-contained for the PO, or shorten them? Chris's call. The rendering is in `schema/intake.py`.
- **Parent key:** `get_item` and `find_items` return the parent as a bare id. `expand=parent` gives its `sequence_id` (Phase 1 §3.1), which makes the key. This is a small adapter PR plus a fake-transport test.
- **`related` as a link:** today it's a description line. A real relation is a new write and needs a conformance case (roadmap/14 §8).
- **Bitwarden:** the cached session locked between the morning read and the run. The server takes its env at launch, so after an unlock, restart the host.
- Next full conformance run: a new `--run-id`, ideally in October, to exercise the date-parsing fix end to end.

---
*Written at session end by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
