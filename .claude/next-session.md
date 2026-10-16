# Next session: Phase 7 step 3, the adapter guide (written 2026-10-16, after step 2)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row 7 and §10 item 4. The kickoff plan and Chris's answers are in memory `phase7-decisions`.
- **Deadline: 2026-10-27**, when the Jira and Confluence trials end.

## Done: step 2, `feat/phase7-readme`
- The README is rewritten for a stranger. It covers what the project is, a quick start, a board-config reference, the four ways to host it, how it works, an evidence list and a "not yet run live" list.
- **Gate passed.** A fresh subagent saw only the README and `examples/` and wrote a config for a described self-hosted Plane board. `server.config.load` loaded it, and every value matched. It found 5 doc gaps, all fixed: `base_url`, the iteration pattern, `{name}`, `taxonomy` and Plane state groups.
- `plane.example.toml` no longer cites the private CONVENTIONS doc, and MODULES.md drops the README's ✅ override.

## Next: step 3, `feat/phase7-adapter-guide`
- A guide for adapter authors:
  - the `adapters/base.py` interface and its errors;
  - adapters stay mechanical, and conventions stay in `server/service.py`;
  - no delete path, and every write is read-proven first;
  - a fake transport plus the conformance suite as the proof.
- Link it from the README's "Proving an adapter" section.
- **Done when (proposed):** a test ties the guide to `base.py`, so every abstract method and error class is named in it, and `uv run pytest` stays green.
- **Then:** step 4 `release` (0.1.0, CHANGELOG, minimal CI; the tag and release wait for Chris's OK), step 5 `gate`, then the AOR case study.

## Chris's calls
- **Who the gate tester is**, before step 5. The repo stays private until the gate passes; the tester gets collaborator access at the tag. If the tester is on Plane's free plan, the `parent`/`label` path needs a live conformance run first.
- **Before 2026-10-27:** run `groom` under a host (AGADM-6), and apply po's pending `plan-cycle` patch (`2d411c31`) on ms01.
- **Before the flip:** re-run step 1's history scan.

## Open follow-ups (not blockers)
- 6c gate findings 3–5: `plan-cycle` proposes in one batch, then commits in another; its read-back opened only 3 of 27 items; Plane's `find_items` returns `fields: {}` without saying so.
- **Older:**
  - Plane's by-key `get_item` has no iteration.
  - "Today" comes from the machine's clock.
  - The throttle should be shared per token.
  - `publish-docs.yml` has never run.

---
*Written by the session-handoff module after `feat/phase7-readme`. If the roadmap has moved on, trust the roadmap over this file.*
