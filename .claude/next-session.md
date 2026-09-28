# Next session: Phase 6 step 3, the `groom` skill (written 2026-09-27)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 (Phase 6 row), §5 layer 3 (`groom` = the PO's review pass), §11 ("what `groom` may change without a human": v1 = nothing; it proposes, the PO applies)
- **Kickoff calls (Chris, 2026-09-27; D-numbers owed to AOR at the Phase 6 catch-up):**
  1. Rollover is the `plan-sprint` skill; the server stays at 11 tools.
  2. `create_iteration` is find-or-create by name, and on Jira it starts a sprint once its dates cover today.
  3. The Agent SDK example is a terminal chat, and the live gate runs through it.
  4. **New in step 2:** `plan-sprint` takes its one yes *before any write*. After the yes it closes, creates, re-reads and moves, and it asks again only if the leftovers changed.
- **Phase 6 PRs (`feat/phase6-<slug>`):** `rollover-read` ✅ → `plan-sprint` ✅ (this PR) → **`groom`** → `agent-sdk` → `gate`.

## Step 2 is done (`feat/phase6-plan-sprint`)
- [skills/plan-sprint/SKILL.md](../skills/plan-sprint/SKILL.md): read → plan → one yes → `close_iteration` → `create_iteration` → re-read → `move_to_iteration` → check.
  - Leftover reads use `limit=200`.
  - Tasks move with their story or bug. A task whose parent isn't moving is left for the PM to decide.
- [tests/test_skills.py](../tests/test_skills.py) checks three things: the plan sections call only reads, the writes run in rollover order, and every iteration read has a limit ≥ 100. 266 tests pass offline.
- It is unproven live. The gate is its first run.

## Step 3: `skills/groom/SKILL.md`, to settle at kickoff
- **Finding the review queue:** `find_items` has no label filter. Should the skill list the board and filter on `review_label`, or should `find_items` take a label (the tool stays one tool)?
- **Confirmation:** is it one yes per item, or one per batch? §11 says the PO applies every change.
- **What a proposal may touch:** title, parent, feature, state (e.g. cancel a duplicate), and clearing the review label.
  - Labels replace the whole set, so the skill calls `get_item` before `update_item`.
- Tie the skill into `test_skills.py` the way `plan-sprint` is tied, and list it in the README.

## Before `agent-sdk`: the framing line
- The hosts' framing line ([README](../README.md), [SOUL.md](../examples/hermes/SOUL.md)) says every ask is work to file, starting with intake. That would misroute a PM's "roll the sprint over" or a PO's "groom".
- The SDK example needs a line that covers all three roles. Hermes `po` likely needs one too.

## Board state (for the gate, Oct 2 or later)
- **Plane `AGADMIN`:** `202610` (Oct 1–31) holds AGADMIN-2 and is active by date from Oct 1. It can close from Oct 2.
- **Jira `AGADM`:** `202610` is future and holds AGADM-2 and its sub-task AGADM-4. `create_iteration("202610")` on or after Oct 1 starts it; that is the first live proof of the start path.
- **The gate:** roll `202610` → `202611` with `plan-sprint`, through the SDK example.
- **Live env:** as in CLAUDE.md. The Plane item's id is in project memory (`plane-bitwarden-item`).

## Open follow-ups (not blockers)
- `server/secrets.py`: resolve an exact item name when several items match.
- Jira: a digit-only iteration name that doesn't exist gives a JQL 400, not NotFound.
- From Phase 5:
  - The Jira status categories.
  - Plane parent keys.
  - Repetition in a split.
  - `related` as a link.
  - No way to read a comment back.

---
*Written at the end of Phase 6 step 2 by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
