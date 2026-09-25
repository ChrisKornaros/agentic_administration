# Next session — Phase 4, Hermes wiring (written 2026-09-24, updated 2026-09-25)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 Phase 4 row, D8, §11 (the ssh question)
- **Suggested branch:** `feat/phase4-hermes`
- **Phase 4 gate:** the same requester transcript from Discord through Hermes on ms01 gives the same result, with no step dropped.

Phase 3 is done (2026-09-24). It passed its gate: [transcripts/2026-09-24-phase3-gate.md](../transcripts/2026-09-24-phase3-gate.md) records AGADMIN-10, a story under epic AGADMIN-6, in Backlog with `needs-review` and three Given/When/Then criteria.

AOR has caught up: roadmap/14 D15–D19 and the §3.3 gate findings (AOR #212), and `stay-in-project-tree` v2 with the `//etc/**` denies (AOR #213, re-vendored here 2026-09-25). Nothing is owed to AOR before Phase 4.

## Do
1. `/phase-kickoff` for Phase 4. Settle §11's ssh question up front: `stay-in-project-tree` denies `ssh`/`scp`/`rsync`. Either Chris runs the ms01 steps himself, or MODULES.md records an exception. ms01 has had its own clone since 2026-09-25 (memory linked, 206 tests pass), so a session opened on ms01 needs no ssh.
2. **Hermes config (D8):**
   - a global `mcp_servers` entry, stdio, running `uv run --directory <repo> python -m server <board.toml>`;
   - the token through `env`;
   - `tools.include` set to the 11 tools;
   - the framing line from the README's Claude Code section in the Hermes persona or system prompt;
   - the skills loaded in whatever way Hermes loads skills. Check its docs first.
3. Run the story gate from Discord, with Chris as the requester. Record it next to the Phase 3 record, and compare the steps with run 2.

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
