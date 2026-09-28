# Next session: Phase 6 step 4, the Agent SDK example (written 2026-09-28)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 (Phase 6 row), §5 layer 4 (the Claude Agent SDK path), §10 done-def #3 (the server runs unchanged under Hermes *and* the SDK example)
- **Phase 6 PRs (`feat/phase6-<slug>`):** `rollover-read` ✅ → `plan-sprint` ✅ → `groom` ✅ (this PR) → **`agent-sdk`** → `gate`.
- **Kickoff calls already made (2026-09-27):**
  - The example is a terminal chat that loads this repo as a plugin: the same server, skills and framing line.
  - `claude-agent-sdk` goes in an optional dependency group, not a runtime dependency.
  - Run `/substrate-preflight` and read the claude-api reference first.
  - The live gate runs through this example and needs a metered Anthropic API key.

## Step 3 is done (`feat/phase6-groom`)
- `find_items` has a `label` filter, and the server still has 11 tools.
  - Jira: a JQL `labels = "…"` clause.
  - Plane: filters after the full list read, ignoring case.
- [skills/groom/SKILL.md](../skills/groom/SKILL.md): read the queue (`find_items(label=<review_label>, limit=100)`) → review each item → one yes → for each item, `get_item` then `update_item` → add a comment on each duplicate → report.
  - Each item gets one of three outcomes: sign off, cancel as a duplicate, or hold.
  - A proposal may change the title, parent, feature or state. It never changes the description, assignees, iteration or other labels.
  - A feature is proposed only where `capabilities.levels.feature` is `container`. Jira's `update_item(feature=…)` is `Unsupported`.
- **Inferred, not asked:** a signed-off story, bug or task moves from Backlog to `todo`, because that is where `plan-sprint` looks for backlog candidates. Epics keep their state. Chris should confirm or overturn this.
- 272 tests pass offline. The skill is unproven live.
- Owed to AOR at the Phase 6 catch-up: D-numbers for the step 1–3 kickoff calls (memory `phase6-decisions` items 1–6, plus the `todo` rule).

## Step 4: settle at kickoff
- **The framing line:** today's line ([README](../README.md), [SOUL.md](../examples/hermes/SOUL.md)) says every ask is work to file, starting with intake. That misroutes a PM's "roll the sprint over" and a PO's "groom". The SDK example needs a line that covers all three roles. Does Hermes `po` get it in this PR or later?
- **Where the example lives:** `examples/agent-sdk/`, and whether `tests/test_examples.py` ties it to the tools the way it ties Hermes.

## Board state (for the gate, Oct 2 or later)
- **Plane `AGADMIN`:** `202610` holds AGADMIN-2 and can close from Oct 2.
- **Jira `AGADM`:** `202610` is still future and holds AGADM-2 and its sub-task AGADM-4. Calling `create_iteration("202610")` on or after Oct 1 starts it.
- **The gate:** roll `202610` → `202611` with `plan-sprint`, through the SDK example. The live env is as described in CLAUDE.md.

## Open follow-ups (not blockers)
- `server/secrets.py`: an exact name match when several items match.
- Jira: a digit-only iteration name that doesn't exist gives a JQL 400 rather than NotFound.
- From Phase 5: status categories, Plane parent keys, repetition in a split, `related` as a link, and no way to read a comment back.

---
*Written at the end of Phase 6 step 3 by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
