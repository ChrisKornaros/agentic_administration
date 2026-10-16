# Next session: Phase 7 step 4, the release (written 2026-10-16, after step 3)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row 7 and §10 item 4. The kickoff plan and Chris's answers are in memory `phase7-decisions`.
- **Deadline: 2026-10-27**, when the Jira and Confluence trials end.

## Done: step 3, `feat/phase7-adapter-guide`
- [adapters/README.md](../adapters/README.md) covers the interface, the errors, "mechanical, not clever", the rules (no delete, read-proven, idempotency, secrets, stdlib), the transport, proof by fake and conformance, and a wiring checklist. The README's "Proving an adapter" section links it.
- [tests/test_adapter_guide.py](../tests/test_adapter_guide.py) ties the guide to `base.py` (every abstract member and error) and to the wiring points. It also fails on a DELETE in any adapter's source (inferred, flagged). 408 tests.

## Next: step 4, `feat/phase7-release`
- Set the version to `0.1.0` in both `pyproject.toml` and `.claude-plugin/plugin.json` (both now say `0.0.1`).
- Write `CHANGELOG.md`.
- Add a minimal CI workflow: `uv sync` + `uv run pytest`.
- Draft the release notes. The README's pre-release banner names 0.1.0.
- **Done when (proposed):** a test ties the two versions to each other and to the CHANGELOG's top entry; `uv run pytest` stays green; the CI workflow runs green on the PR.
- **Chris approves the tag and the GitHub release after the merge.** No PyPI.
- **Then:** step 5 `gate`, then the AOR case study.

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
*Written by the session-handoff module after `feat/phase7-adapter-guide`. If the roadmap has moved on, trust the roadmap over this file.*
