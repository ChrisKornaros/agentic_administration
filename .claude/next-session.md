# Next session: Phase 7, publish, then the stranger's gate (written 2026-10-26, after `docs/live-setup-ci-runs`)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row 7 and §10 item 4. The plan and Chris's answers are in memory `phase7-decisions`.
- **The Jira and Confluence trials end 2026-10-27.** After that, only Plane is left on Chris's side.

## Done on 2026-10-26
- **`docs/setup-guide` (PR #46):** [SETUP.md](../SETUP.md); the shared-status guard; a stranger agent's rehearsal folded in.
- **`docs/live-setup-ci-runs`:**
  - **Chris's self-test.** It passed: author-run and agent-led, on `AGADM` ([record](../transcripts/2026-10-26-setup-self-test.md)).
  - **Knowledge conformance, run `20261026`:** 11/11, with wikilinks and backlinks.
  - **`publish-docs.yml`, live,** through the private throwaway repo `ChrisKornaros/agkb-docs-check` with a read PAT (7-day expiry).

## Next: publish
1. **Before the flip:** re-run step 1's history scan, and scan the PR bodies and comments (#1 onward).
2. **Chris's call: the tag.** 0.1.0 was never tagged. Either tag `e9d8aba` as planned, with `[Unreleased]` going into 0.2.0, or re-cut 0.1.0 to include everything (one release PR: versions, `uv lock`, the CHANGELOG, the README status line).
3. **Flip the repo public**, then the GitHub release (Chris approves both).
4. **Before 2026-10-27:** reject po's held `plan-cycle` patch (`2d411c31`) on ms01 (the 6c gate record, finding 8).

## Then: the stranger's gate (Phase 7 step 5)
- A friend, on the public repo and a free Jira site: "Please set this up for my organization: <URL>". This also covers Jira below Premium. Record it like the self-test.
- **Then:** the AOR case study.

## For an AOR session
- roadmap/14: the graph publish plus groom's rules step as D44 (inferred); the D26 amendment; the gate's new shape (agent-led setup; the self-test as the author's run).
- Lessons:
  - AOR's h2 re-read guard blocks a second Read of a *different* range of the same file.
  - Write a rules fixture against the skill it tests.
  - Rehearse a setup guide with a fresh agent against a stand-in tracker before a person runs it.

## Open follow-ups (not blockers)
- `describe` should list the project's Scrum boards when `board_id` is wrong, and a read-only command should read one item back. Without them, the self-test's agent wrote its own REST scripts (finding 1).
- `describe` checks status names only: not transitions, board columns or Cancelled's category.
- The board templates' comments cite private design references.
- 6c gate findings 3–5; Plane's by-key iteration; "today" from the clock; the throttle per token.
- A YAML block scalar (`key: |`) shows a lone `|` in the front-matter table.
- An easier install: a `marketplace.json`, and a config drafted from `describe`.

---
*Written by the session-handoff module after `docs/live-setup-ci-runs`. If the roadmap has moved on, trust the roadmap over this file.*
