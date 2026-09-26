# Next session — AOR catch-up, then Phase 5 (Jira Cloud Premium) (written 2026-09-26)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 Phase 5 row, D2, §11 (Jira iteration ownership)
- **Suggested branch (here):** `feat/phase5-jira-<step>`, one PR per step
- **Phase 5 gate:** conformance passes against a personal Jira Cloud site (never a company site).

Phase 4 is done (2026-09-26). It passed its gate: [transcripts/2026-09-26-phase4-gate.md](../transcripts/2026-09-26-phase4-gate.md) records AGADMIN-11, a story under epic AGADMIN-6, filed from Discord through Hermes on ms01 with every run-2 step present. The wiring is [examples/hermes/](../examples/hermes/). On ms01 it runs as the Hermes `po` profile (its own Discord bot, Opus 5.5), with this repo mounted read-only as compose-override mount 4.

## AOR is owed first (a separate AOR session, as after Phase 3)
1. **roadmap/14:** Phase 4 ✅ 2026-09-26, and a §3.4 from the gate record's findings. §3.1 says Hermes registers tools as `mcp_<server>_<tool>`; the gate showed `mcp__board__<tool>`. Also record the calls this session settled: the Hermes profile is `po` (Chris: the PO's job is to manage the board), the gate ran Opus 5.5, and `skills.write_approval: true`. §11's ssh question can close, since ms01 sessions need no ssh.
2. **`hosts/ms01/hermes/`:** the deployed `docker-compose.override.yml` now has mount 4 (this repo, `:ro`, at `/home/chris/agentic_administration`) and says "four" in its header. AOR's copy still has three. Add `profiles/po/config.fragment.yaml`, the ms01 copy of this repo's example: model `claude-opus-5-5`, ms01 paths, `write_approval: true`. Add a README row for the `po` profile.

## Then Phase 5 here
1. `/phase-kickoff` for Phase 5, then `/substrate-preflight` for Jira Cloud (a new vendor surface: rate limits, the Premium tier, ToS).
2. **Ask Chris first:** is there a personal Jira Cloud Premium site (a trial works) to run conformance against? It must never be a company site. The adapter can't be read-proven without one.
3. Read-proven first: a dated read-only probe of the site (issue types, custom hierarchy levels, workflows and transitions, the board and sprint ids), then the adapter, then conformance.

## To run / verify
- `uv run pytest`: 208 pass, offline. `claude plugin validate .` last passed 2026-09-24 on the Mac, with one expected warning about the root CLAUDE.md. It isn't on ms01's shell PATH, and Phase 4 didn't touch the plugin.
- Hermes on ms01: `docker exec hermes hermes -p po mcp test board` shows 11 tools. The po gateway state is in `~/.hermes/profiles/po/gateway_state.json`.

## Open questions / follow-ups (not Phase 5 blockers)
- **Parent key:** `get_item`, `find_items` and `commit_item` return the parent as a bare id, seen again in the Phase 4 gate. `expand=parent` gives its `sequence_id` (Phase 1 §3.1), which makes the key. This is a small adapter PR plus a fake-transport test.
- **Split repetition:** every story in a split repeats the request's whole problem and outcome. Keep items self-contained for the PO, or shorten them? Chris's call. The rendering is in `schema/intake.py`.
- **`related` as a link:** still a description line. In the Phase 4 gate the agent added a back-pointer comment after a yes, and Chris found that enough for now. A relation write needs a conformance case first (roadmap/14 §8).
- **No comment read:** the server can add a comment but not read one back, so the gate checked the AGADMIN-9 comment by the write's result and by eye.
- Next full conformance run: a new `--run-id`, ideally in October, to exercise the date-parsing fix end to end.

---
*Written at session end by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
