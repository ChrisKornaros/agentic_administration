# Next session: Phase 7, the flip and the release, then the stranger's gate (written 2026-10-26, after `feat/phase7-release-recut`)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row 7 and §10 item 4. The plan and Chris's answers are in memory `phase7-decisions`.
- **The Jira and Confluence trials end 2026-10-27.** After that, only Plane is left on Chris's side. Nothing below needs them.

## Done on 2026-10-26
- **Pre-flip scans: clean.** They covered 104 commits over 94 refs (the 47 `refs/pull/*` heads included), every PR body, comment, review and issue, and the 8 CI logs. There were no token-shaped strings, no real sites or private hosts, and no stray emails. The only UUIDs in the logs are the runners' temp paths. Chris confirmed that only dummy values were ever used, so a names scan has nothing to find.
- **Deleted, with Chris's yes:** Plane's GitHub bot (`makeplane[bot]`) had left 6 auto-link comments on #10, #13, #18, #29, #32 and #40, with the workspace slug, real ids and item titles. All 6 are gone.
- **The re-cut (this PR):** 0.1.0 now includes everything; `[Unreleased]` was folded in. The versions didn't change.

## Next: the flip (Chris approves each step)
1. **Chris:** disconnect Plane's GitHub integration from this repo first. Otherwise it keeps posting on public PRs.
2. **Chris, if it's still pending:** reject po's held `plan-cycle` patch (`2d411c31`) on ms01 (the 6c gate record, finding 8).
3. Re-check that nothing new landed: `gh api repos/ChrisKornaros/agentic_administration/issues/comments --jq length` should be `0`.
4. **The flip:** `gh repo edit ChrisKornaros/agentic_administration --visibility public --accept-visibility-change-consequences`.
5. **The release:** `gh release create v0.1.0 --target <this PR's merge sha> --title v0.1.0 --notes-file <the 0.1.0 entry>`. Relative links don't resolve on a release page, so make them absolute. If the merge lands after the 26th, fix the entry's date first, in a tiny PR.

## Then: the stranger's gate (Phase 7 step 5)
- A friend, on the public repo and a free Jira site: "Please set this up for my organization: <URL>". This also covers Jira below Premium. Record it like the self-test.
- **Then:** the AOR case study.

## For an AOR session
- roadmap/14: the graph publish plus groom's rules step as D44 (inferred); the D26 amendment; the gate's new shape (agent-led setup; the self-test as the author's run).
- Lessons:
  - AOR's h2 re-read guard blocks a second Read of a *different* range of the same file.
  - Write a rules fixture against the skill it tests.
  - Rehearse a setup guide with a fresh agent against a stand-in tracker before a person runs it.
  - Before a flip, scan bot comments too: a tracker's GitHub app posts ids and item titles that no git scan sees. CI logs carry v4 UUIDs (runner temp paths) that aren't ids.

## Open follow-ups (not blockers)
- `describe` should list the project's Scrum boards when `board_id` is wrong, and a read-only command should read one item back (self-test finding 1).
- `describe` checks status names only: not transitions, board columns or Cancelled's category (now a known issue in the CHANGELOG).
- The board templates' comments cite private design references.
- 6c gate findings 3–5; Plane's by-key iteration; "today" from the clock; the throttle per token.
- A YAML block scalar (`key: |`) shows a lone `|` in the front-matter table (now a known issue).
- An easier install: a `marketplace.json`, and a config drafted from `describe`.

---
*Written by the session-handoff module after `feat/phase7-release-recut`. If the roadmap has moved on, trust the roadmap over this file.*
