# Next session: Phase 6c step 5, plan-cycle (written 2026-10-08, after step 4's templates)

- **Source:** AOR [roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md) §9 row **6c**, **D42** (a skill that plans a full cycle, one yes before any write), **D32** (`plan-sprint`, the pattern it follows), §3.7 (the Food Content run). Phase 7 follows 6c.
- **Deadline: 2026-10-27.** The Jira and Confluence Premium trials end that day. The open items below that need Jira still have to land before then.

## The 6c plan (kickoff 2026-10-05, Chris confirmed)
Six PRs: `probe` ✅ → `board-types` ✅ → `dates-fields` ✅ → `templates` ✅ → **`plan-cycle`** → `gate`. The kickoff's answers and inferred items are in project memory (`phase6c-decisions`).

## Done: step 4, `feat/phase6c-templates` (D41's template half + D42's argument)
`[templates.<name>]` in the board config: `level` (story by default), `title` (a `{month}` `{year}` pattern filled from the item's start date, else its target date), `description` (a Markdown skeleton whose `{description}` takes the request's text), `feature`, `labels`, `fields`, `state`, `days` (weekdays) and `dates` (`target` | `start` | `both`), all checked at load. `propose_item(template=…)` fills the item from it. The request's title, feature and dates win, and its labels and field values are added. `describe_board` lists the templates. A retried commit now also finishes the state when the item is still in `backlog`, since Jira transitions after the create. The calendar example has a `cycle` epic template and a `post` story template. Offline only, since there's no new wire call. 373 tests.

Inferred, not asked (flag for the AOR catch-up as D41/D42 amendments): the key names above; the title placeholders and their date; the `{description}` slot (a skeleton without one refuses a request's description); the request-wins and merge rules; a template refuses `level` and `intake`; the server carries the cadence but doesn't enforce it (the skill uses it); the retry's state fix.

## Next: step 5, `feat/phase6c-plan-cycle`
- A new product skill, `skills/plan-cycle/SKILL.md`: frontmatter `name` + `description` only, tools named bare, only the 11 board tools. Tie it into [tests/test_skills.py](../tests/test_skills.py) (the skill set, its call order) the way `plan-sprint` is.
- Its shape (D42, kickoff): reads first (`describe_board` for the templates and their cadence, `get_iteration` / `find_items` for what exists). Then it generates the whole cycle: the epic from the epic template, then one story per slot (each story template's `days` across the cycle's dates, with `dates` saying which date). The PM edits the list. Then it shows the exact write-up of every item, field and call and takes one yes. Then the writes: `create_iteration` (find-or-create), the epic's propose → commit, and each story's propose → commit under the epic in the cycle. A read-back diff comes after.
- Settle at the start: the `intake_id` / `part` scheme for cycle items, so a rerun finds what exists; what a slot whose title or caption isn't known yet gets; whether the framing line (README, `SOUL.md`, `chat.py`, tied by [tests/test_examples.py](../tests/test_examples.py)) routes "plan November" to plan-cycle on every host; and whether `create-story` uses a template for a one-off item on a calendar board.
- Done when `uv run pytest` passes above 373 with plan-cycle tied into the skill tests.

## Then: step 6, the gate
Hermes `po` on Discord plans Food Content `202611` with only config. Before it, FCONTENT gets a Bug type, and its config drops the `bug` label mapping and the review label, and gains `[fields]` for its two Story properties plus its templates (exact write-up first). ms01 needs a Food Content board config (a second profile, or po switched to that board).

## After 2026-10-27
- Re-run the read-only Confluence probe on Free (§11).

## Open follow-ups (not blockers)
- **Plane `get_item` by key reports no iteration** (gate finding 6): the by-key read returns `cycle_id: null`. Fix the adapter and the fake.
- **Today comes from the machine's date** (gate finding 7) in both adapters.
- **No Jira sprint is active** until `202611` is started. Chris's call before Oct 27.
- `groom` hasn't run under a host. `AGADM-6` is its first real item, before Oct 27.
- **Food Content for the rest of October** is still unplanned.
- Plane's `get_item` costs a GET per property on the item's type; fine at two properties, worth watching on a board with many.
- `publish-docs.yml` has never run in GitHub Actions (private until Phase 7). Plane's renderer has no tables. The Phase 5 items carry over.

---
*Written by the session-handoff module after `feat/phase6c-templates`. If the roadmap has moved on, trust the roadmap over this file.*
