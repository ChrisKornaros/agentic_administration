# Next session: Phase 6 step 2, the `plan-sprint` skill (written 2026-09-27)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 (Phase 6 row), §5 layer 3 ("rollover = close + move remaining"), §11 (`groom`)
- **Kickoff calls (Chris, 2026-09-27; D-numbers owed to AOR at the Phase 6 catch-up):**
  1. Rollover is the `plan-sprint` skill combining the existing tools. The server stays at 11 tools.
  2. `create_iteration` is find-or-create by name. On Jira it also starts a sprint made ahead of time once its dates cover today.
  3. The Agent SDK example is a terminal chat.
  4. The live gate runs through that SDK example.
- **Phase 6 is five PRs, `feat/phase6-<slug>`:** `rollover-read` (step 1, this PR) → `plan-sprint` → `groom` → `agent-sdk` → `gate`.

## Step 1 is done (`feat/phase6-rollover-read`)
- `find_items(iteration=…)` returns the items whose *current* iteration it is, a closed one included:
  - Plane reads `cycles/{id}/cycle-issues/`.
  - Jira uses JQL `sprint =` and then filters, because the Sprint field keeps closed sprints.
- `create_iteration` is find-or-create by name, as above.
- The conformance `rollover` case passed live on both boards on 2026-09-27: Jira **10/10**; Plane **9 pass + 1 skip**. Findings are in [conformance/README.md](../conformance/README.md#what-the-2026-09-27-rollover-runs-settled-phase-6):
  - Both trackers let an item leave a closed iteration with a plain move.
  - Jira carries a moved story's sub-tasks, done ones too.
- 262 tests pass offline.

## Step 2: `skills/plan-sprint/SKILL.md`
- **The order is fixed by Jira's one-active-sprint rule:**
  1. `close_iteration(old)`
  2. `create_iteration(next)`, which finds or creates it and starts it on its first day
  3. `find_items(iteration=old)`, keeping what is neither done nor cancelled
  4. show the plan, including what comes in from the backlog, and wait for one yes
  5. `move_to_iteration`
- **Pass a generous `limit`** (e.g. 200). The tool's default of 20 can cut a busy sprint's leftovers.
- **Move tasks together with their story or bug.** On Jira, sub-tasks follow their parent anyway, and a sub-task moved on its own is unproven.
- **Plane closes a cycle only after its start day.** Jira closes only an active sprint.
- Tie the skill into [tests/test_skills.py](../tests/test_skills.py) the same way the Phase 3 skills are, and list it in the README layout.

## To run / verify
- `uv run pytest`: 262 pass, offline.
- **Live Plane:** `PLANE_API_KEY_BW_ITEM=<the Plane item's id> PLANE_API_KEY_BW_FIELD=API BW_SESSION="$(cat ~/.cache/bw_session)"`. The id is in project memory (`plane-bitwarden-item`), and the name `Plane` is ambiguous in the vault.
- **Live Jira:** as in CLAUDE.md.

## Board state now (for the gate)
- **Plane `AGADMIN`:**
  - `202609` is closed. The done task stayed in it.
  - `202610` (Oct 1–31) holds AGADMIN-2.
  - It will be active by date on Oct 1.
- **Jira `AGADM`:**
  - `202609` is closed.
  - `202610` is future and holds AGADM-2 and its sub-task AGADM-4.
  - On or after Oct 1, `create_iteration("202610")` starts it. That is the first live proof of the Jira start path.
- **Gate timing:** Plane can close `202610` from Oct 2, so the gate (roll `202610` → `202611`) runs Oct 2 or later, through the Agent SDK example.

## Open follow-ups (not blockers)
- **`server/secrets.py` could resolve an exact item name** when `bw get item <name>` matches several items.
- **Jira: a digit-only iteration name that doesn't exist** becomes a JQL 400, not NotFound. `_sprint_id` treats digit-only strings as ids.
- Carried from Phase 5:
  - The Jira status categories (To Do and Cancelled).
  - Plane parent keys (`expand=parent`).
  - Repetition in a split.
  - `related` as a link.
  - No way to read a comment back.

---
*Written at the end of Phase 6 step 1 by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
