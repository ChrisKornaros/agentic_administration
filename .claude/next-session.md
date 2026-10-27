# Next session: Phase 7's last gate, the setup at Chris's company, then the AOR case study (written 2026-10-27, after `docs/post-release-handoff`)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row 7 and §10 item 4. The plan and Chris's answers are in memory `phase7-decisions`.
- **The Jira and Confluence trials ended 2026-10-27.** Only Plane is left on Chris's side. The gate below runs on the company's tracker, not on the trials.

## Done on 2026-10-27
- **PR #49:** `plan-cycle` now carries the lessons from po's held patches. All four patches are rejected on ms01.
- **Plane's GitHub integration is off this repo.** It stays on AOR, content_manager and product_use_tracker.
- **The flip:** the repo is public. It had 0 comments just before.
- **The release:** [v0.1.0](https://github.com/ChrisKornaros/agentic_administration/releases/tag/v0.1.0) is out.
  - The tag is on `8b1e3c9`, PR #49's merge.
  - The notes are the 0.1.0 entry, with its links made absolute to `blob/v0.1.0/`.

## Next: the setup gate at Chris's company (Phase 7 step 5)
- **The run:** Chris runs [SETUP.md](../SETUP.md) at work, with a fresh agent, the public URL and "Please set this up for my organization: https://github.com/ChrisKornaros/agentic_administration". This replaces the friend on a free Jira site (Chris, 2026-10-27).
- **Settle before the run: who drives the agent.** (Inferred, not asked.)
  - If a coworker types the request and answers the agent, the run is the stranger's gate. "The setup by someone other than the author" then leaves the README's not-yet-run-live list.
  - If Chris drives, the run is a second author run. It proves a team's own board, but that line stays.
  - Either way, a plan below Premium also proves "Jira below Premium".
- **The company stays out of this repo (D9):**
  - The run happens on the company's side. This repo's sessions never read or write the company's site.
  - The record comes from what Chris brings back. It goes in `transcripts/<date>-company-setup.md`, shaped like [the self-test's](../transcripts/2026-10-26-setup-self-test.md).
  - The record holds steps, checks and outcomes only. It carries no company name, site, project key, people or item text.
  - `tests/test_public.py` catches a real `*.atlassian.net` site but not a name. Read the record and the PR body for names before the commit.
- **Afterwards:**
  - Remove the lines the run proved from the README's not-yet-run-live list ([README.md:511](../README.md#L511)). The released 0.1.0 entry stays as it is; the change goes under `[Unreleased]`.
  - The run's findings go under the follow-ups below.
- **Then:** the AOR case study (`case-studies/agentic-administration/`, §3.9, row 7 ✅, done-def #4).

## For an AOR session
- roadmap/14: the graph publish plus groom's rules step as D44 (inferred); the D26 amendment; the gate's new shape (agent-led setup; the self-test as the author's run; the company run).
- Lessons:
  - AOR's h2 re-read guard blocks a second Read of a *different* range of the same file.
  - Write a rules fixture against the skill it tests.
  - Rehearse a setup guide with a fresh agent against a stand-in tracker before a person runs it.
  - Before a flip, scan bot comments too: a tracker's GitHub app posts ids and item titles that no git scan sees. CI logs carry v4 UUIDs (runner temp paths) that aren't ids.
  - A host that patches its own skills (Hermes `skill_manage`) re-stages the same lesson on every run until the upstream skill carries it. Read its held patches as skill gaps, and fix the source.
  - Release notes cut from a CHANGELOG entry need absolute links, pinned to the tag (`blob/v<version>/`), since relative ones don't resolve on a release page.

## Open follow-ups (not blockers)
- `describe` should list the project's Scrum boards when `board_id` is wrong, and a read-only command should read one item back (self-test finding 1).
- `describe` checks status names only: not transitions, board columns or Cancelled's category (a known issue in the CHANGELOG).
- The board templates' comments cite private design references.
- 6c gate finding 5: `find_items`' description doesn't say Plane returns `fields` empty (the skill now does). Also: Plane's by-key iteration; "today" from the clock; the throttle per token.
- A YAML block scalar (`key: |`) shows a lone `|` in the front-matter table (a known issue).
- An easier install: a `marketplace.json`, and a config drafted from `describe`.

---
*Written by the session-handoff module after `docs/post-release-handoff`. If the roadmap has moved on, trust the roadmap over this file.*
