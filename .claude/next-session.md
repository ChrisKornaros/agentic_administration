# Next session: Phase 7, the flip and the release, then the stranger's gate (written 2026-10-27, after `chore/plan-cycle-po-lessons`)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row 7 and §10 item 4. The plan and Chris's answers are in memory `phase7-decisions`.
- **The Jira and Confluence trials end 2026-10-27.** After that, only Plane is left on Chris's side. Nothing below needs them.

## Done on 2026-10-26 and 27
- **Pre-flip scans: clean** (memory `phase7-decisions`). Plane's bot comments are deleted, and 0.1.0 was re-cut to include everything.
- **po's `plan-cycle` patches (this PR).**
  - Since the 6c gate, po had staged four `skill_manage` patches: `2d411c31`, `aef58cab`, `6ed4269a` and `355dd165`. Each one carried the same lessons.
  - The skill now carries those lessons:
    - the read-back reads every item, and reads around the Plane gaps;
    - the call is `get_item(ref=…)`, in groom and plan-sprint too;
    - a PM-changed state goes through `update_item`;
    - slots may be proposed in a batch (Chris, 6c finding 3).
  - All four patches are rejected on ms01, and the pending queue is empty. The 0.1.0 entry is dated 2026-10-27.

## Next: the flip (Chris approves each step)
1. **Chris:** disconnect Plane's GitHub integration from this repo first. Otherwise it keeps posting on public PRs.
2. Re-check that nothing new landed: `gh api repos/ChrisKornaros/agentic_administration/issues/comments --jq length` should be `0`.
3. **The flip:** `gh repo edit ChrisKornaros/agentic_administration --visibility public --accept-visibility-change-consequences`.
4. **The release:** `gh release create v0.1.0 --target <this PR's merge sha> --title v0.1.0 --notes-file <the 0.1.0 entry>`. Use this PR's merge sha, not `8134655`. Relative links don't resolve on a release page, so make them absolute. If the merge lands after the 27th, fix the entry's date first, in a tiny PR.

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
  - A host that patches its own skills (Hermes `skill_manage`) re-stages the same lesson on every run until the upstream skill carries it. Read its held patches as skill gaps, and fix the source.

## Open follow-ups (not blockers)
- `describe` should list the project's Scrum boards when `board_id` is wrong, and a read-only command should read one item back (self-test finding 1).
- `describe` checks status names only: not transitions, board columns or Cancelled's category (now a known issue in the CHANGELOG).
- The board templates' comments cite private design references.
- 6c gate finding 5: `find_items`' description doesn't say Plane returns `fields` empty (the skill now does). Also: Plane's by-key iteration; "today" from the clock; the throttle per token.
- A YAML block scalar (`key: |`) shows a lone `|` in the front-matter table (now a known issue).
- An easier install: a `marketplace.json`, and a config drafted from `describe`.

---
*Written by the session-handoff module after `chore/plan-cycle-po-lessons`. If the roadmap has moved on, trust the roadmap over this file.*
