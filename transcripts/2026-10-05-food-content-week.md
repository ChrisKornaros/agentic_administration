# First real-board run: a week of content on Food Content (2026-10-05)

The product's first write outside the throwaway boards. Chris asked for a
dry run of planning one week of his Food Content board, his personal
calendar board on Plane. The plan was to roll `202609` over to `202610`
and file October's epic plus one story per post day from Oct 5 to Oct 11,
then lock it in if the plan looked right. **Done:** `FCONTENT-131` (the
epic) and `FCONTENT-132`…`137` (six stories) are filed, signed off and in
`202610`. A field-by-field read-back matched the approved write-up.

This isn't a phase gate. It's the first time the product met a board
that isn't a software board, and most of what it found is there (findings
1–4). This is a summary: item titles, captions and field values stay out
of git.

## Setup

- **Host:** a Claude Code dev session (Opus 5.5, `claude-opus-5-5`). It
  drove the eleven tools in process through the SDK's client,
  `Client(build(BoardService(PlaneAdapter(cfg))))`, the same server
  `python -m server` runs over stdio. The agent followed the skills by
  hand. No host loaded them.
- **Board:** Plane project `FCONTENT`. The config is `boards/food-content.toml`
  (gitignored), copied from the Plane example and fitted to the board.
- **Skills followed:** `intake` (step 3, the board's own search),
  `create-epic` (propose → commit, epic first), `groom` (sign-off) and
  `plan-sprint` (rollover, then the move). Step 3 skipped `search_docs`:
  this board has no docs, and the `knowledge` config points at the AGKB
  test space.
- **Approval:** Chris approved the board fix, then asked for an exact
  write-up of every item, field and call before the lock-in, and approved
  that. CLAUDE.md's "throwaway boards only" rule is unchanged. This run
  was Chris's explicit exception for his own board.

## The run

| Step | What happened |
|---|---|
| Read | `describe_board` found 3 problems: no `Bug` work-item type, no `needs-review` label, and none of the config's taxonomy labels on the board |
| Board fix (outside the product) | Created the labels `needs-review` and `bug` (2 POSTs). The config maps `bug = { label = "bug" }`, and the taxonomy lists the labels the board already uses. `describe_board` is then clean |
| Dry run | `describe_board`, `find_items` (no October epic yet), `get_iteration("202609")` (closed by date), `find_items(iteration="202609")` (one unfinished item, the September epic), then 7 × `propose_item`: no warnings, no `existing`. 18 calls, all GET |
| Write-up | Every item's type, title, state, parent, module, labels, assignee, description, dates and properties, plus each call in order. Chris approved it |
| 1. `plan-sprint` | `close_iteration("202609")`: a no-op. `update_item("FCONTENT-111", state="done")`: the September epic, Chris's call. `create_iteration("202610", 2026-10-01, 2026-10-31)`: active |
| 2. `create-epic` | 7 × propose → commit, epic first, then each story with `parent="#epic"`. Every preview matched |
| 3. Outside the product | Target dates (and the epic's start date), and the Story type's two custom properties: 7 PATCHes and 10 POSTs to `…/work-item-properties/{id}/values/` (an upsert). Every value was read back |
| 4. `groom` | `find_items(label="needs-review")`, then for each item `get_item` + `update_item`: the label cleared, and the stories moved Backlog → `todo`. The epic kept its state, then went to `in_progress` (the PM's call) |
| 5. `plan-sprint` | `move_to_iteration` (7 items → `202610`), then `find_items(iteration="202610")`: all 7 there. The review queue is empty |
| Read-back | A read-only diff of every field against the write-up. Everything matched. Its one flagged difference was the check's own: it compared text with the HTML stripped, so a Markdown bullet showed up as a change |

The wire, all steps: no DELETE.

## Findings

| # | Finding | Disposition |
|---|---|---|
| 1 | **Config alone didn't fit a non-software board.** The product requires a Bug level and the review label. A content board has no Bug type and no review label, so every write, propose included, refused until two labels were added outside the product. | Open: this is the Phase 7 gate ("only config"). Options: make `bug` optional per board, or add a Bug type to every project (Chris, 2026-10-05). A roadmap call (D38+). |
| 2 | **The model has no dates.** Every story on a calendar board has a post date, and the epic spans the month. | Open. Set by a script outside the product this time. |
| 3 | **The model has no custom fields.** The board's Story type carries two properties (a boolean and a multi-select) that every post fills. | Open. Set by the same script. Plane's write is `POST …/work-item-properties/{id}/values/` with `{"value": …}`: a boolean, or a list of option ids when the property is multi-valued. The upsert was read back. |
| 4 | **The intake renderer doesn't fit captions.** An intake record renders Problem / Outcome / Acceptance criteria, but on this board the description *is* the post's caption skeleton. | Open. Used `propose_item`'s direct form (`description=…`), which keeps propose → commit and the `external_id` idempotency. Templates per story type would close it. |
| 5 | The server's `title` case capitalizes small words, and the board's own titles don't. | None. Chris chose the server's: titles live only in Plane. |
| 6 | `groom`'s sign-off and `plan-sprint`'s move ran live for the first time, on a real board. | Partly closes "`groom` hasn't run live". It still hasn't run under a host. |
| 7 | The run stopped after its first write: a bug in the driver script, not the product. Its tool helper's own `name` parameter clashed with `create_iteration(name=…)`. Rerunning from the top changed nothing twice: the close was a no-op, the state write was idempotent, and `create_iteration` and `commit_item` would have found what existed. | None in the product. It confirms the reruns the skills promise are safe. |
| 8 | On a real board, Chris wanted the exact write-up, not the skills' plan summary, before any write. | Practice: show the exact write-up first, every field and call. |

Left on the board by this run: `202610`, the seven items above,
`FCONTENT-111` now Done, and the two unused labels `needs-review` and
`bug`.
