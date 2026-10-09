# Next session: Phase 6c step 7, the gate (written 2026-10-09, after step 6's multi-board server)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row **6c** (gate: a full Food Content cycle planned through the product with only config, nothing written outside it), **D38–D42**, §3.7 (the Food Content run). The multi-board server (D43) isn't in the roadmap yet: it goes into the AOR catch-up after the gate. Phase 7 follows 6c.
- **Deadline: 2026-10-27.** The Jira and Confluence Premium trials end that day. The open items below that need Jira still have to land before then.

## The 6c plan (kickoff 2026-10-05; re-planned 2026-10-09, Chris confirmed)
Seven PRs: `probe` ✅ → `board-types` ✅ → `dates-fields` ✅ → `templates` ✅ → `plan-cycle` ✅ → `multi-board` ✅ → **`gate`**. On 2026-10-09, after the ms01 session, Chris ruled out a Hermes profile or a server per board: one `po` sits above every board, and the gate also tests that. The decisions are in project memory (`phase6c-multi-board`).

## Done: step 6, `feat/phase6c-multi-board` (D43, offline)
`python -m server boards/` serves every board config in the directory, each named by its file stem. A TOML with no `backend` there, such as a docs config, is skipped. A file named directly must be a board. All 11 tools take `board`, so there are still 11 tools (D13). The argument is optional when one board is loaded, so the existing single-board hosts are unchanged. With several boards:
- `describe_board()` lists them from their configs (name, `description`, backend, type, project) without reading a tracker.
- Any other call without a board is refused.
- The propose and commit results name the board, and `commit_item(token, board)` refuses a token proposed on another board.

The four skills that start a request (intake, plan-sprint, plan-cycle, groom) share one board step: use the board the request names, else list the boards and ask. Each then passes `board` on every call and names the board before every yes. The create skills work on intake's board, and plan-cycle's write-up starts with the board. The framing line now says "one of the team's boards" in all three hosts. The Hermes example points at `boards/` with every backend's token. 398 tests.

Decided by Chris on 2026-10-09:
- po asks which board unless the request names it.
- Docs stay one tree per host, Chris's "one core knowledge base for a company or person". Narrowing it per board (a label or a page subtree inside that tree) is a possible follow-up and isn't built.
- The gate's po serves **FCONTENT + AGADMIN only**.

Inferred, not asked (flag as D43 in the AOR catch-up):
- Boards are named by file stem.
- The optional top-level `description` key.
- The directory's skip rule.
- Board names are unique ignoring case.
- `board` is optional with one board.
- The cross-board commit refusal.
- The framing line's wording.

## Next: step 7, the gate, `feat/phase6c-gate`
Before the run, in this order, each with an exact write-up first:
1. **Mac:**
   - Chris adds a Bug type to FCONTENT in Plane's UI.
   - The gitignored `boards/food-content.toml` changes:
     - `bug` back to `type = "Bug"`;
     - no review label;
     - `board_type = "calendar"`;
     - `[fields]` for its two Story properties;
     - its templates: an epic template, plus the post templates with their `days`;
     - a `description`.
   - Give `boards/agentic_administration.toml` a `description` too, so the board list says it's the AGADMIN throwaway board. Its stem doesn't say "AGADMIN".
   - Run `describe_board(board="food-content")`, read-only, until it's clean.
2. **ms01:**
   - Pull the repo, since po loads `skills/` in place.
   - Copy `boards/food-content.toml` and `boards/agentic_administration.toml`. Not `agadm.toml`, because the gate covers FCONTENT and AGADMIN only.
   - Re-copy `examples/hermes/SOUL.md`. Its framing line changed again.
   - Point po's `config.yaml` board server at `boards/`. The docs config there is skipped. The Plane key already covers both boards, so no new env is needed.
   - Do one gateway restart. A pull doesn't reach the running servers, and the restart also restarts every other profile in the container (memory `ms01-hermes-layout`). `describe_board()` should then list the two boards.
3. **The run:**
   - Chris asks po in Discord to plan November on Food Content.
   - He also sends one request that names no board, to see po ask.
   - Then write a summary in `transcripts/` (keys and checks, no board content), update the README status, and mark 6c done.
- **Done when** po lists the two boards, takes FCONTENT from the request (or asks when the request names no board), names the board in the plan-cycle write-up and gets one yes. 202611's epic and its slots are then on FCONTENT, the read-back matches the write-up, and nothing is written to AGADMIN.

## After the gate
- **AOR catch-up:** D43 and the step-5 D42 amendments, with the 6c gate result. Its edits:
  - §6's config shape gains `description` and the directory form;
  - §5's layer 3 becomes one server per host;
  - row 6c's gate wording.
- Re-run the read-only Confluence probe on Free (§11) after 2026-10-27.

## Open follow-ups (not blockers)
- **Plane `get_item` by key reports no iteration** (gate finding 6): the by-key read returns `cycle_id: null`. Fix the adapter and the fake. plan-cycle's read-back works around it with `find_items(iteration=…)`.
- **Today comes from the machine's date** (gate finding 7) in both adapters.
- **No Jira sprint is active** until `202611` is started. Chris's call before Oct 27.
- `groom` hasn't run under a host. `AGADM-6` is its first real item, before Oct 27.
- **Food Content for the rest of October** is still unplanned. plan-cycle on `202610` could cover it, since past days get no slot. It's Chris's call.
- **One key, several throttles** (step 6 review): each board has its own adapter and throttle. Two Plane boards on one key, called in parallel, can reach the per-key rate limit twice as fast. It's harmless while po works one board at a time. Share the throttle per token before many boards see concurrent use.
- **One broken board config stops every board** (by design in step 6): fail-fast at start. Revisit if a bad file on ms01 ever takes po down.
- **More boards on po:** Chris's other Plane boards each need a config and a clean `describe_board`. AGADM needs the Jira env in po's board server. Neither is part of the gate.
- Plane's `get_item` costs a GET per property on the item's type. That's fine at two properties and worth watching on a board with many. plan-cycle's read-back calls it once per item.
- `publish-docs.yml` has never run in GitHub Actions (private until Phase 7). Plane's renderer has no tables. The Phase 5 items carry over.

---
*Written by the session-handoff module after `feat/phase6c-multi-board`. If the roadmap has moved on, trust the roadmap over this file.*
