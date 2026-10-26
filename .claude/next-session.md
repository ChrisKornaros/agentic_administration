# Next session: Phase 7 step 5, the gate (written 2026-10-26, after `docs/setup-guide`)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row 7 and §10 item 4. The plan and Chris's answers are in memory `phase7-decisions`.
- **Deadline: 2026-10-27**, when the Jira and Confluence trials end.

## Done: `docs/setup-guide`, added before the tag at Chris's ask
- [SETUP.md](../SETUP.md): the setup in order, for an agent given the repo's URL ("set this up for my organization") or a person. The README and CLAUDE.md point to it; `tests/test_setup.py` ties it to the code.
- A config whose two states share a status now fails to load: a done item read back as cancelled.
- `describe` flushes its JSON, so its verdict comes last when captured.
- An agent rehearsed the guide against a stand-in Jira board (a new project, missing Backlog and Cancelled). It asked rather than mapped around them, and its 20 doc gaps were triaged into the guide. 440 tests.

## Gate, reshaped by Chris (2026-10-26)
- **Today: Chris's self-test.** A fresh directory outside `~/vault`, Claude Code under a fresh `CLAUDE_CONFIG_DIR`, and "Please set this up for my organization: <repo URL>". Chris answers as the org admin (Jira, `AGADM`, board 2, Claude Code, the Jira Bitwarden item). Then the chat's read, and one write after a yes. Afterwards, read both session JSONLs and the board (read-only), and record it in `transcripts/` as "author-run, agent-led".
- **Later: a friend's test** on the public repo and a free Jira site. That one is the stranger's gate, and it also covers "Jira below Premium".

## Also today, on the Confluence trial
- **Knowledge conformance, live**, with the new wikilinks. It needs a new empty AGKB page from Chris and a gitignored config with that parent.
- **`publish-docs.yml`, live**, through the private throwaway repo `ChrisKornaros/agkb-docs-check`. Its files are in the session scratchpad: three pages under "Team Docs" (1310721) with the label `md-ci`, and the workflow pinned to `5001a36` with a read PAT. It needs Chris's three secrets (`JIRA_USER`, `JIRA_API_TOKEN`, `PUBLISHER_READ_TOKEN`).
- Record both in `conformance/README.md` and the README's evidence, in one PR.

## Then: publish
- **Before the flip:** re-run step 1's history scan, and scan the PR bodies and comments (#1 onward).
- **Chris's call: the tag.** 0.1.0 was never tagged. Either tag `e9d8aba` as planned, with `[Unreleased]` going into 0.2.0, or re-cut 0.1.0 to include everything.
- **Before 2026-10-27:** reject po's held `plan-cycle` patch (`2d411c31`) on ms01 (the 6c gate record, finding 8).

## For an AOR session
- roadmap/14: the graph publish and groom's rules step as D44 (inferred), and the D26 amendment (front matter shown, wikilinks, backlinks).
- Lessons:
  - AOR's h2 re-read guard blocks a second Read of a *different* range of the same file (hit again 2026-10-26).
  - Write a rules fixture against the skill it tests (finding 3).
  - Rehearse a setup guide with a fresh agent against a stand-in tracker before a person runs it. It found 20 gaps, the worst being Jira transitions and board columns.

## Open follow-ups (not blockers)
- `describe` checks status names only, not transitions, board columns or Cancelled's category.
- The board templates' comments cite private design refs (`roadmap/14 §6`, D-numbers).
- 6c gate findings 3–5.
- Plane's by-key iteration; "today" from the clock; the throttle per token.
- A YAML block scalar (`key: |`) shows a lone `|` in the front-matter table.
- An easier install: a `marketplace.json` for `/plugin install`, and a config draft from `describe`'s output.

---
*Written by the session-handoff module after `docs/setup-guide`. If the roadmap has moved on, trust the roadmap over this file.*
