---
name: plan-cycle
description: Plans a whole cycle from the board's templates. It drafts the cycle's epic and one dated item for each slot in the templates' weekday cadence, lets the PM edit the list, and shows the exact write-up of every item, field and call. After one yes, it finds or creates the cycle and files the epic, then each item under it. Use when a PM asks to plan a month or a cycle on a board whose templates set a cadence (a content calendar), or to add a dated item to a cycle.
---

# Plan a cycle

You work for the PM who plans the board's cycles, not for a requester. A
board that plans dated work (a content calendar, a hobby project) plans a
cycle all at once. It has an epic named for the cycle and one item for
each dated slot, each filled from one of the board's templates. The tool
names are the server's, and your host may add a prefix.

This skill only files new work. Closing the previous cycle and moving its
unfinished work is the plan-sprint skill's job. Nothing is deleted.

## 1. Read the board

Call `describe_board()` and keep the result.

If it returns `boards`, the server serves several. Use the board the
request names, by its name, its project or its description. If it names
none, list the boards with their descriptions and ask which one. Don't
choose one yourself. Then call `describe_board(board="<board>")` and keep
that result instead. Pass that `board` on every call, and name the board
in everything you show before a yes.

If `problems` is not empty, stop. Every write refuses until the operator
fixes the board, so list the problems for them. Note `naming`,
`iterations`, `containers` (the features), `labels`, `fields` (each with
its kind and options),
`capabilities.backend` and `templates`.

- **The epic template** is the one whose `level` is `epic`. If there are
  several, ask the PM which one. If there is none, the cycle gets no epic
  and its items stand alone.
- **The slot templates** are the ones with `days`. Each lists the weekdays
  it fills (`mon` to `sun`). Its `dates` says which of an item's dates the
  slot's day sets: `target`, `start` or `both`.
- If no template has `days`, the board has no cadence to plan by. Say so
  and stop. To roll a sprint over, use plan-sprint. To file one request,
  use intake.

## 2. Name the cycle and read it

- **The cycle** is the one the PM names, or else the one after the active
  one by the board's naming. With `YYYYMM`, "plan November" is `202611`,
  from 2026-11-01 to 2026-11-30. For any other pattern, ask the PM for the
  name and dates.
- If it's already in the board's `iterations`, read it with
  `get_iteration("<cycle>")` and use its dates as they are. If it's
  closed, stop and say so.
- Read what's already in it with `find_items(iteration="<cycle>", limit=200)`.
  Never call it empty without that read.
- Look for the cycle's epic, which may sit outside the cycle:
  `find_items(level="epic", query="<the epic's title>", limit=5)`.

## 3. Draft the plan

**The ids.** The plan's id is the cycle's first day plus `-cycle`, for
example `20261101-cycle`. It comes from the cycle, not from today's date.
Every run for this cycle makes the same id, so a rerun finds what an
earlier run filed. Each item has a part name:

- The epic is `epic`.
- A slot is `<template>-<date>`, for example `post-2026-11-02`. A second
  slot from the same template on the same day gets `-2`, then `-3`.

The server makes each item's external id `<id>/<part>`, for example
`20261101-cycle/post-2026-11-02`.

**The items.**

1. **The epic,** from the epic template. Its dates are the cycle's first
   and last day, and its title is the template's pattern filled from the
   start date ("November 2026 Content"), or the PM's when the template has
   no pattern. It goes in the cycle too, except
   when `capabilities.backend` is `jira`: there an epic stays out of
   sprints, and its dates span the cycle.
2. **The slots.** For each slot template, make one slot on every day of the
   cycle whose weekday is in its `days`. If the cycle is already active,
   leave out the days already past. Each slot takes the template's
   feature, labels, state and field values. Its day goes into
   `target_date`, `start_date` or both, as the template's `dates` says.
   Its parent is the epic, and it goes in the cycle.
3. **Titles and descriptions.** Ask the PM what each slot is, such as a
   post's title and caption. They can give some now and the rest later.
   - **Title:** the PM's, written in the board's `naming.item_case`. With
     none, the template's own title pattern fills it. Without a pattern,
     use a placeholder of the template's name and the day, such as
     "Post For Monday, November 2".
   - **Description:** the PM's text goes where the template's skeleton
     says `{description}`. With no text, the item gets the skeleton alone.
     A skeleton without `{description}` takes no text.
4. **What's already there,** from step 2's reads:
   - An item whose `external_id` is one of this plan's was filed by an
     earlier run. It is that slot or the epic, already on the board.
   - An item on a slot's day, of the same level and feature, was filed
     some other way. Show the pair, and leave the slot out unless the PM
     keeps it.
   - An epic from step 2 that is already this cycle's becomes the parent.
     Don't file another.
   - Anything else in the cycle stays as it is.

**The PM edits.** They may drop a slot, move one to another day (its part
name follows the day), add one from any template, or switch a slot to
another template. They may also change a slot's title, description,
feature, labels or field values. Fields go by their names in `fields`, and
options by their option names. The state comes from the template, because
`propose_item` doesn't take one. To add one item to a cycle that's already
planned, plan only that slot. Show the list again after each change.

## 4. Check, then show the write-up and wait for one yes

1. **Check against the board.** The cycle and the epic may not exist yet,
   so check without them. For one slot of each template, and for each slot
   whose feature, labels or fields the PM changed, call
   `propose_item(template="<name>", intake_id="<id>", part="<part>", …)`
   with that slot's values but no `parent` or `iteration`. It writes
   nothing. If it fails, or warns about anything but an item already on
   the board (`existing`), fix the plan and check again. The tokens are
   simply dropped.
2. **Show the exact write-up,** in the order the calls will run:
   - The board, by name.
   - The cycle: its name and dates, whether it exists or will be created,
     and whether it is active or upcoming, with the `create_iteration`
     call and its arguments.
   - The epic: its title, dates, labels, state and iteration, with its
     `propose_item` call and arguments, then `commit_item`. If it's
     already on the board, show its key too.
   - Every slot, by day: its part name, title, dates, feature, labels,
     state, each field with its value, the whole description as it will
     land, and its calls with their arguments. A slot already on the
     board shows its key.
   - Next to the slots, list the items already in the cycle, the slots
     they cover, and what is left alone.
   - End with the counts: how many items are created, and how many are
     already on the board.

   Wait for one clear yes before any write. If the PM changes anything,
   update the plan, check what changed, and show the write-up again. The
   board's `confirm` mode applies to filing items, not to this: always
   wait.

## 5. Write, in this order

1. **The cycle.** Call
   `create_iteration("<cycle>", start="<first day>", end="<last day>")`,
   or give only the name when it already exists. If it fails, stop, pass
   the message on, and say that nothing was written.
2. **The epic.** Call
   `propose_item(template="<epic template>", intake_id="<id>", part="epic", start_date="<first day>", target_date="<last day>", iteration="<cycle>")`,
   without `iteration` on Jira. Compare the preview with the write-up. It
   matches when the call didn't fail, `warnings` has nothing but the note
   about `existing` (item 4), and the title, dates, labels, fields and
   state are the ones shown. If it matches, call `commit_item(token)`
   right away with no second question, because the PM approved exactly
   this. Keep the epic's key. If the plan's epic was filed some other way
   (step 3), skip this and use its key.
3. **Each slot, by day.** Call
   `propose_item(template="<name>", intake_id="<id>", part="<part>", title="<title>", description="<text>", target_date="<day>", parent="<the epic's key>", iteration="<cycle>")`.
   Send `start_date` instead of `target_date`, or both, as the template's
   `dates` says. Add `feature`, `labels` or `fields` only where the slot
   differs from its template. Compare in the same way, and if it matches,
   call `commit_item(token)`.
4. **If `existing` is set,** an earlier run filed that item. Commit anyway.
   `commit_item` returns that item instead of a duplicate and fills in only
   what an interrupted run left unset.
5. **When a preview differs, stop on that item and ask about it alone.**
   For a failure, fix the slot and say what changed. For a suggested
   title, ask which one they want. Propose that item again, and once they
   agree, carry on with the rest.
6. **Read it back.** Call `find_items(iteration="<cycle>", limit=200)` and
   check that every item filed into the cycle is there. Then read each one with
   `get_item("<key>")`, and compare its title, dates, feature, labels,
   state, fields and parent with the write-up.

**If a write fails:**
- **Rate limit, edge wall, or tracker unreachable:** wait as the message
  says, then retry the same call. A retried `commit_item` never creates a
  duplicate.
- **Expired or unknown token:** propose that item again. Commit without
  asking only if the new preview still matches.
- **Anything else:** stop, pass the message on, and say which items
  landed. Running this skill again is safe. `create_iteration` finds the
  cycle, and the same ids find every item that landed.

## 6. Report back

- Give the cycle's name, its dates and whether it's active or upcoming,
  and the epic's key.
- List every item by day with its key and title, and mark the ones that
  were already on the board.
- Say where the read-back differs from the write-up, or that it matches.
- List the slots that still have a placeholder title or no description,
  so the PM knows what to fill in later.
