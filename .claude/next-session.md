# Next session: Phase 6c step 7, the gate (written 2026-10-09, after step 6's multi-board server)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row **6c**, **D38–D42**, §3.7. The multi-board server (D43) isn't in the roadmap yet; it goes into the AOR catch-up after the gate. Phase 7 follows 6c.
- **Deadline: 2026-10-27**, when the Jira and Confluence trials end.

## The 6c plan (re-planned 2026-10-09, Chris confirmed)
`probe` ✅ → `board-types` ✅ → `dates-fields` ✅ → `templates` ✅ → `plan-cycle` ✅ → `multi-board` ✅ (#39) → **`gate`**. Chris's call: one `po` above every board, and the gate tests that too. The decisions and inferred items are in project memory (`phase6c-multi-board`).

## Done: step 6 (D43, offline, 398 tests)
- `python -m server boards/` serves each board config in the directory (a TOML with no `backend` is skipped). All 11 tools take `board`, optional with one board.
- With several boards, `describe_board()` lists them from the configs, and a call that names no board is refused. Previews name the board, and a token never commits on another board.
- The four skills that start a request ask which board unless the request names it. Docs stay one tree per host.

## Next: step 7, the gate, `feat/phase6c-gate` (show an exact write-up before each step)
1. **Mac:**
   - Chris adds a Bug type to FCONTENT in Plane's UI.
   - The gitignored `boards/food-content.toml` gets: `bug = { type = "Bug" }`, no review label, `board_type = "calendar"`, `[fields]` for the two Story properties, an epic template plus post templates with `days`, and a `description`.
   - `boards/agentic_administration.toml` gets a `description` that names AGADMIN, since its file name doesn't.
   - Run `describe_board(board="food-content")`, read-only, until it's clean.
2. **ms01** (memory `ms01-hermes-layout`):
   - Pull the vault checkout.
   - Copy only those two board files.
   - Re-copy `SOUL.md`, whose framing changed.
   - Point po's board server at `boards/`.
   - Restart the gateway, which restarts every profile. `describe_board()` should list the two boards.
3. **Run:** in Discord, Chris asks po to plan November on Food Content, plus one request that names no board, to see po ask.
- **Done when** po names FCONTENT in the plan-cycle write-up and gets one yes, 202611's epic and its slots are on FCONTENT, the read-back matches the write-up, and nothing lands on AGADMIN. Then a `transcripts/` summary (keys and checks only), the README status, and 6c done.

## After the gate
- **AOR catch-up:** D43, step 5's D42 amendments, §6's `description` and directory form, and §5 layer 3.
- After Oct 27: re-run the read-only Confluence probe on Free (§11).

## Open follow-ups (not blockers)
- **Shared key, separate throttles:** each board has its own throttle, so Plane boards on one key can hit its rate limit faster in parallel. Share the throttle per token before concurrent use. One broken board config stops every board (fail-fast, by design).
- Plane `get_item` by key reports no iteration (gate finding 6).
- Today comes from the machine's date (gate finding 7).
- No Jira sprint is active until `202611` starts. Chris's call before Oct 27.
- `groom` hasn't run under a host. AGADM-6 is first, before Oct 27.
- Food Content for the rest of October: plan-cycle on `202610` could cover it. Chris's call.
- More boards on po need configs, and AGADM needs the Jira env.
- `publish-docs.yml` has never run in Actions. The Phase 5 items carry over.

---
*Written by the session-handoff module after `feat/phase6c-multi-board`. If the roadmap has moved on, trust the roadmap over this file.*
