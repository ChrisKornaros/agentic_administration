# Next session: Phase 6 step 5, the live rollover gate (written 2026-09-28)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 (Phase 6 row: "Rollover verified on Plane and Jira"), §10 done-def #3 (the server runs unchanged under Hermes *and* the SDK example)
- **Phase 6 PRs (`feat/phase6-<slug>`):** `rollover-read` ✅ → `plan-sprint` ✅ → `groom` ✅ → `agent-sdk` ✅ (this PR) → **`gate`**. It can't run before **Oct 2**.

## Step 4 is done (`feat/phase6-agent-sdk`)
- [examples/agent-sdk/chat.py](../examples/agent-sdk/chat.py) is a terminal chat that loads the repo as a plugin.
  - Model: Opus 5.5, at the CLI's default effort (medium).
  - Tools: `Skill` plus the 11 board tools, and nothing else. It loads no settings and runs in an empty temporary working directory.
  - Reads (the server's read-only tools) run without asking; each write waits for a `y`.
  - The API key resolves through `server/secrets.py`: `ANTHROPIC_API_KEY`, or `ANTHROPIC_API_KEY_BW_ITEM`.
- **The framing line is option A** (Chris, 2026-09-28): one line routing all three roles. It's in the README, Hermes `SOUL.md` and the example, and `tests/test_examples.py` ties them together.
- **Proven offline only.** The proof was a capture against a local `ANTHROPIC_BASE_URL` stub. The example has never called the real API.

## Before the gate (Chris)
- **A metered Anthropic API key.** Best in its own workspace with a low spend limit, which doubles as the kill switch.
  - Put it in a Bitwarden item and use `ANTHROPIC_API_KEY_BW_ITEM`.
  - Save the item id to project memory, as with `plane-bitwarden-item`.
- **Hermes:** check that ms01's `~/.hermes/profiles/po/SOUL.md` has the new line (copied after merge), then send one Discord request to prove it. This isn't part of the gate.

## The gate: roll `202610` → `202611` with `plan-sprint`, through the SDK example
- **Plane `AGADMIN`:** `202610` holds AGADMIN-2. It can close from Oct 2.
- **Jira `AGADM`:** `202610` is still future and holds AGADM-2 and its sub-task AGADM-4. `create_iteration("202610")` on or after Oct 1 starts it.
- **Afterwards:**
  - Find the transcript by the printed session id under `~/.claude/projects/`, and check the board read-only.
  - Write `transcripts/<date>-phase6-gate.md`.
  - Update the README status line: rollover is live.
- **Then the Phase 6 AOR catch-up:** D-numbers for memory `phase6-decisions` items 1–7.

## Open follow-ups (not blockers)
- **The README's Claude Code command** still gives the full set of Claude Code built-in tools. The SDK example and Hermes give only the board. Align them, or keep the command as the Phase 3 gate proved it?
- **A cosmetic stderr notice.** The example prints Claude Code's "claude.ai connectors are disabled" notice on a machine that's logged in to claude.ai.
- **Carried over:**
  - `server/secrets.py`: an exact name match when several items match.
  - Jira: a digit-only iteration name that doesn't exist gives a JQL 400 rather than NotFound.
  - The Phase 5 items.

---
*Written at the end of Phase 6 step 4 by the session-handoff module. If the roadmap has moved on, trust the roadmap over this file.*
