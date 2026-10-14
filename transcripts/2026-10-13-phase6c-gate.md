# Phase 6c gate: a month of a content calendar, planned from Discord (2026-10-13)

The gate, from AOR roadmap/14 §9 Phase 6c: *a full Food Content cycle is
planned through the product with only config, and nothing is written
outside it.* The 2026-10-09 re-plan added multi-board (D43, inferred, for
AOR): one Hermes profile serves two boards and asks which one when a
request names none. **PASS.** po asked when no board was named, named
FCONTENT in its write-up, took one yes, and filed `202611`'s epic and 26
slots. A read-back of every item matched the approved write-up, and
nothing landed on AGADMIN. The gate's Jira half (dates and custom fields,
live) passed on 2026-10-08 ([conformance/README.md](../conformance/README.md)).

This is a summary. Titles, captions, module names and field values are
board content, so they stay out of git. The raw sessions are in po's
`state.db` on ms01.

## Setup

- **Host:** Hermes, profile `po`, in Docker on ms01, from Discord. The
  model is Opus 5.5 (`claude-opus-5-5`). `main` at `4e68f0c` (#39), with the
  vault checkout mounted read-only.
- **Board server:** `python -m server boards/agentic_administration.toml
  boards/food-content.toml`, which serves two boards. It names the two files
  rather than `boards/` (finding 10). The `knowledge` server is unchanged.
  `SOUL.md` is the repo's copy.
- **Restart:** po's gateway restarted alone (`s6-svc -r` on `gateway-po`),
  and the other profiles kept running. Discord reconnected with 7 skills.
- **Boards:** Plane `FCONTENT`, Chris's own calendar board (real, not
  throwaway; his explicit call, as on 2026-10-05), and `AGADMIN`, the
  throwaway software board. FCONTENT's config:
  - `board_type = "calendar"`, a Bug type (added in Plane's UI), review off;
  - two `[fields]` on the Story type;
  - an epic template with a `{month} {year}` title;
  - two slot templates with `days`: four weekdays and two weekdays.
- **Before (read-only, in po's container):**
  - Both `describe_board` calls are clean, and `describe_board()` lists the
    two boards with their descriptions.
  - FCONTENT has 131 items (highest key 137), no `202611`, and nothing
    dated in November.
  - AGADMIN has 23 items (highest key 23), and its `202611` holds AGADMIN-2
    and AGADMIN-3.
- **PM:** Chris, in plain words, in three Discord threads, each a session
  of its own.

## The run (CDT)

| Thread | What happened |
|---|---|
| 1. 17:46, "what boards can you see?" | `describe_board()` with no board: the list from the configs, no tracker read. po named both boards with their descriptions and asked which to work on |
| 2. 17:53, a story request that names no board | `skill_view` (intake, create-story), `describe_board()`, then Hermes' `clarify` with the two boards as its choices. No board picked, no preview, nothing written. Chris's reply went to thread 1 by mistake, so the question timed out at 60 minutes. po then said it had stopped and filed nothing (finding 2) |
| 3. 17:58, "let's plan November on Food Content" | `plan-cycle`, below |

**Thread 3, `plan-cycle`:**

| Step | What happened |
|---|---|
| Read | `describe_board()`, then `describe_board(board="food-content")`. Then `find_items` three times: `iteration="202611"`, the epic by title, and the epic's `external_id`. All empty |
| Check | 3 × `propose_item`: the epic and one slot of each template, no `parent` or `iteration`. No warnings |
| Write-up 1 (61 s after the ask) | The board by name. `create_iteration("202611", 2026-11-01, 2026-11-30)`, upcoming. The epic's title, dates, label, state and cycle. 26 slots by day: part name, placeholder title and target date, with each template's fields and the call shapes. Totals: 27 new, 0 on the board. po asked about Nov 26, a US holiday, and asked for titles, captions and modules |
| PM edit | A monthly theme and a dish list, a weekly baking slot, a weekly grocery photo, and placeholders for the rest |
| Write-up 2 | po read `202610` (`find_items`) for the board's own patterns and checked 4 more previews (no warnings). Same structure as write-up 1: a module on 16 slots, a PM title on 16, and every description word for word (7 slots and the epic). It asked two questions: keep the holiday slot, and which module the pie goes under |
| Yes | One: keep the holiday slot as shown, "otherwise yes, please proceed" |
| Write, 18:23:38–18:30:08 | `create_iteration`. Epic `propose_item` → `commit_item`: FCONTENT-138. Then 26 × `propose_item` in one batch and 26 × `commit_item` in one batch: FCONTENT-139…164 (finding 3). No failure, no warning, no `existing` |
| po's read-back | `find_items(iteration="202611")`: all 27. Then `get_item` on 3 of the 27, after 3 calls the host refused for a wrong argument name (findings 4–7) |
| `skill_manage` | A patch to `plan-cycle`, held for approval and not saved (finding 8) |
| Report, 18:31 | The cycle, the epic's key, and every slot by day with its key. It said it had opened only 3 items, and listed the placeholders left to fill |

## Read back afterwards (read-only, every item)

| Check | Result |
|---|---|
| `202611` | 27 items, FCONTENT-138…164, nothing else |
| Epic FCONTENT-138 | Level, title, label, state, start and target dates, no parent, and description: all as written up |
| 26 slots | Level, title, label, Todo, target date = its day, no start date, parent FCONTENT-138, module, description, and both custom fields: all as written up. The one difference is in the write-up itself (finding 9) |
| FCONTENT | 158 items, highest key 164: the baseline plus 27 |
| AGADMIN | 23 items, highest key 23, `202611` still holds AGADMIN-2 and AGADMIN-3: unchanged |

The writes were 1 `create_iteration` and 27 `commit_item` calls, all on
FCONTENT. Nothing was written outside the product, and nothing was deleted.

## The gate's conditions

| Condition | Result |
|---|---|
| Asks which board when a request names none | PASS (thread 2) |
| The plan-cycle write-up names FCONTENT and gets one yes | PASS |
| `202611`'s epic and its slots are on FCONTENT | PASS: FCONTENT-138 and 139…164 |
| The read-back matches the write-up | PASS (the full read-back above; po's own was partial, finding 4) |
| Nothing lands on AGADMIN | PASS |
| Only config, nothing written outside the product | PASS |

## Latency

The service serializes adapter calls, so the batches ran one call at a
time:
- each `propose_item` took 4–5 s;
- each `commit_item` took 6–10 s, so the 26 commits took 3 min 22 s;
- from the yes to the last commit took 6 min 40 s.

Every token was committed within 6 minutes of being issued (the TTL is
30 minutes).

## Findings

| # | Finding | Disposition |
|---|---|---|
| 1 | Board choice held both ways, live. A named board was used without asking (thread 3). An unnamed one was asked about, with the boards as choices and no pick (thread 2). | None needed. D43's ask-unless-named rule passes from a host. |
| 2 | When the question timed out, po called the content board "the likely home" while still asking. It neither chose nor wrote. | None needed now. The skills forbid choosing a board, not suggesting one. Chris's call whether they should forbid suggesting too. |
| 3 | po proposed all 26 slots, compared the previews, then committed all 26. The skill says each slot is proposed, compared and committed in turn, by day. | A follow-up: decide whether `plan-cycle` allows the batch. A bigger cycle or a slower tracker could outlast the 30-minute token TTL; the skill already proposes again when a token expires. |
| 4 | po's read-back opened 3 of the 27 items with `get_item`, where the skill says each one. It said so in its report. | A follow-up for `plan-cycle`'s read-back, tied to finding 5. |
| 5 | On Plane, `find_items` returns `fields: {}`. The adapter reads property values only in `get_item` (one GET per property per item), and `find_items`' description doesn't say so. po took it for a display quirk. | A follow-up: say so in `find_items`' description, or leave `fields` out of list results. |
| 6 | Plane's by-key `get_item` reports no iteration (Phase 6 gate, finding 6), seen again. po read cycle membership from the list. | The existing follow-up. |
| 7 | po's first 3 `get_item` calls named the argument `key` (the field items carry) instead of `ref`. Hermes refused them before the server saw them, and the retry worked. | None needed. Noted for the tool docs. |
| 8 | po tried to patch `plan-cycle` through `skill_manage`, with findings 3, 5, 6 and 7 as tips. `skills.write_approval` held it for the operator, and nothing was saved. Phase 4's guard held live. | Chris rejects the pending patch. Its content is in this table instead. |
| 9 | Write-up 2's totals line was off: it said 14 PM titles and 12 placeholders, but the table had 16 and 10. Its title column also carried a holiday emoji as a marker on one slot, while the call and the board have the title without it. The total (27) and every value that landed matched. | None in code: the approved rows are what landed. Noted, since the write-up is what the PM approves. |
| 10 | ms01's `boards/` also holds the Jira board config, and po's board server passes only the Plane key. Pointed at `boards/`, po would have listed AGADM and failed on its first call there. Naming the two files gave exactly the gate's boards. | The README's Hermes paragraph now says to name the files to serve only some. |

Left on the board by this run: `202611` (Nov 1–30, upcoming),
FCONTENT-138 (Todo), and FCONTENT-139…164 (Todo). 10 slots keep
placeholder titles, and 19 slots have no caption yet.
