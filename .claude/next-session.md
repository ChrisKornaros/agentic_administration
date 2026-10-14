# Next session: Phase 7 step 2, the README for a stranger (written 2026-10-14, after step 1)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row 7 and §10 item 4. The kickoff plan and Chris's answers are in memory `phase7-decisions`.
- **Deadline: 2026-10-27**, when the Jira and Confluence trials end.

## Done: step 1, `feat/phase7-public-audit`
- The tree and every commit were scanned. Nothing was found: no token, no board config or report, no live id or site, and no company or client name. Chris confirmed that no work content ever touched the repo.
- `tests/test_public.py` now guards the tree on every run. It refuses a tracked board-content path, a token-shaped string, a v4 UUID and a real Atlassian site.
- The README no longer claims a `generic` backend; the parent-plus-label mapping is flagged as never run live. It also says the `roadmap/14 D<n>` citations point to a private repo.

## Next: step 2, `feat/phase7-readme`
- Rewrite the README for a stranger: what it is, a quick start (clone, `uv sync`, an example config, `describe`), the three hosts, and the evidence as a short list.
- **Done when:** a fresh subagent with only the README and `examples/` writes a config for a described Plane board that `server.config` loads, and `test_examples` stays green.
- **Then:** step 3 `adapter-guide`, step 4 `release` (0.1.0, CHANGELOG, minimal CI; a tag and release only), step 5 `gate`, then the AOR case study.

## Chris's calls
- **Who the gate tester is**, before step 5. The repo stays private until the gate passes; the tester gets collaborator access at the tag.
- If the tester uses Plane's free plan, the parent-plus-label path needs a live conformance run first.
- **Before 2026-10-27:** `groom` under a host (AGADM-6); po's pending `plan-cycle` patch (`2d411c31`) on ms01.
- **Before the flip:** re-run step 1's history scan, since steps 2–5 add commits.

## Open follow-ups (not blockers)
- The 6c gate findings: `plan-cycle` batches its proposes, then its commits (3); its read-back opened only 3 of 27 items (4); Plane's `find_items` returns `fields: {}` without saying so (5).
- **Older:** Plane's by-key `get_item` has no iteration; today comes from the machine's date; share the throttle per token; `publish-docs.yml` has never run.

---
*Written by the session-handoff module after `feat/phase7-public-audit`. If the roadmap has moved on, trust the roadmap over this file.*
