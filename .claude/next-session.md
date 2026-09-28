# Next session: AOR catch-up for Phase 5, then Chris picks what's next (written 2026-09-27)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 (Phase 5 row, then Phase 6), §4, §11
- **Deadline still running:** the Jira site's Premium trial ends **2026-10-27**. After that it drops to Free, and sprints keep working. Nothing Premium-only is in use: Initiative and Feature collapse.

Phase 5 is done (2026-09-27). Its gate passed: the Jira conformance suite ran **PASS 9/9** on the first live run against the company-managed Scrum project `AGADM` (board 2), with no DELETE. The dated result and findings are in [conformance/README.md](../conformance/README.md#what-the-2026-09-27-jira-run-settled).

It took three PRs:
1. The probe (#14).
2. The adapter (#15).
3. Conformance (`feat/phase5-jira-conformance`).

## AOR is owed first (a separate AOR session, as after Phases 3 and 4)
1. **roadmap/14:**
   - Mark Phase 5 ✅ 2026-09-27.
   - Add a **§3.5** with the findings from the probe and conformance:
     - Jira takes a sub-task straight under an epic, so the model is the guard.
     - The old `/search` is gone (410).
     - JQL matches labels exactly, and the `xid:` label works as the idempotency key.
     - Sprints keep their dates when started.
     - A closed sprint's refusal message.
     - The 401 CAPTCHA rule.
   - D-numbers for the five 2026-09-27 calls:
     - Feature collapses to a `feature:<name>` label.
     - Initiative collapses to a description line.
     - The `xid:<external_id>` label is the idempotency key.
     - States map by name, through transitions.
     - A sprint whose dates cover today starts on create.
2. **The roadmap/14 §4 table's Jira column is wrong.** Premium's custom levels sit only *above* Epic, so Feature can't be a Jira level. Both optional levels collapse on Jira.
3. **§11:** "Iteration ownership on Jira" is answered by `connection.board_id` (one board per config), and the README says so in `jira.example.toml`.
4. **Transferable lessons** for AOR modules or CONVENTIONS:
   - A fake transport should model a vendor's *live* behavior, not its docs. The Jira fake enforced the documented adjacency rule, and live Jira broke it.
   - The `.gitignore` bug: `boards/` also ignored `examples/boards/`.

## Then, Chris's call on order (don't guess)
- **Chris's Atlassian-tooling project.** He flagged it on 2026-09-27 to build and test after the Jira phase. It's unblocked now.
- **Phase 6 (roadmap):** `plan-sprint` / `close_iteration` rollover, plus the `groom` skill, plus the Claude Agent SDK example bot. The gate is rollover verified on Plane *and* Jira.

## To run / verify
- `uv run pytest`: 256 pass, offline.
- `uv run python -m adapters.jira describe boards/jira-agadm.toml`: a live read, with no writes.
- Credentials: `JIRA_API_TOKEN_BW_ITEM` and `JIRA_USER_BW_ITEM` both name the Jira item, plus `JIRA_USER_BW_FIELD=username`, plus `BW_SESSION="$(cat ~/.cache/bw_session)"`. The site URL is in project memory (`jira-site`) and the gitignored board config.
- The next Jira conformance run needs a new `--run-id` in October: `202609` is closed on board 2, and only one sprint can be active.

## Open follow-ups (not blockers)
- **Jira statuses:** To Do and Cancelled still sit in the `indeterminate` category. Chris planned to move Cancelled into Done (and To Do into To Do).
- **A sub-task moved into a sprint on its own is unproven.** The run moved it together with its story.
- **Parent key on Plane:** reads return the parent as a bare id (a small PR using `expand=parent`). Jira's reads already carry the parent's key and level.
- **Split repetition:** every story in a split repeats the whole request. This is Chris's call; the rendering is in `schema/intake.py`.
- **`related` as a link:** it's still a description line. A relation write needs a conformance case first.
- **No comment read:** the server can add a comment but can't read one back.

---
*Written at the end of Phase 5 by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
