# Next session: Phase 7 step 5, the gate (written 2026-10-19, after step 4)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row 7 and §10 item 4. The kickoff plan and Chris's answers are in memory `phase7-decisions`.
- **Deadline: 2026-10-27**, when the Jira and Confluence trials end.

## Done: step 4, `feat/phase7-release`
- Version `0.1.0` in `pyproject.toml`, `.claude-plugin/plugin.json` and `uv.lock`. Both MCP servers now report it to a host; before, they reported `""` (inferred, flagged).
- [CHANGELOG.md](../CHANGELOG.md), in Keep a Changelog format: what 0.1.0 adds, what hasn't run live, and four known issues.
- [.github/workflows/test.yml](../.github/workflows/test.yml): `uv sync --locked` + `uv run pytest` on every push to `main` and every PR.
- [tests/test_release.py](../tests/test_release.py) ties the versions, the CHANGELOG's top entry and its release link, the README's status line, and the servers' reported version. It also ties CI to the README's commands. 414 tests.
- The release notes are drafted in that PR's body: the CHANGELOG entry plus an install block.

## First: the tag, if it isn't there
- If `gh release view v0.1.0` fails, the tag is still waiting for Chris's yes. Then run `gh release create v0.1.0 --target main --title v0.1.0 --notes-file <the PR body's notes>`. No PyPI.

## Next: step 5, `gate`
- Someone other than Chris points it at a tracker with only config. Record it in `transcripts/`.
- **Then:** the AOR case study.

## Chris's calls
- **Who the gate tester is.** The repo stays private until the gate passes; the tester gets collaborator access at the tag. If the tester is on Plane's free plan, the `parent`/`label` path needs a live conformance run first.
- **Before 2026-10-27:** run `groom` under a host (AGADM-6), and apply po's pending `plan-cycle` patch (`2d411c31`) on ms01.
- **Before the flip:**
  - Re-run step 1's history scan.
  - Scan the PR bodies and comments (#1 onward). They go public with the repo but aren't in git, so step 1's scan didn't cover them.

## Open follow-ups (not blockers)
- 6c gate findings 3–5: `plan-cycle` proposes in one batch, then commits in another; its read-back opened only 3 of 27 items; Plane's `find_items` returns `fields: {}` without saying so.
- **Older:**
  - Plane's by-key `get_item` has no iteration.
  - "Today" comes from the machine's clock.
  - The throttle should be shared per token.
  - `publish-docs.yml` has never run.
- The CHANGELOG lists the Plane, throttle and "today" items as known issues. A fix ships with an entry under the next version.

---
*Written by the session-handoff module after `feat/phase7-release`. If the roadmap has moved on, trust the roadmap over this file.*
