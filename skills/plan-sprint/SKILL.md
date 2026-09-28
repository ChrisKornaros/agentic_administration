---
name: plan-sprint
description: Rolls the current sprint over into the next. It reads what is unfinished in the current iteration, lets the PM bring in ready backlog items, and shows the whole plan. After one yes, it closes the old iteration, finds or creates the next one, and moves the work. Use when a PM or PO asks to end, roll over or plan a sprint (a cycle on some trackers).
---

# Plan a sprint

You work for the PM or PO who plans the team's iterations, not for a
requester. Rollover means three things. The old iteration closes. The next
one exists. The unfinished work moves into it, along with whatever the PM
brings in from the backlog. The tool names are the server's, and your host
may add a prefix.

Nothing is deleted. An item the PM leaves out stays in the closed
iteration, and a later move can still take it out.

## 1. Read the board

Call `describe_board()` and keep the result. If `problems` is not empty,
stop. Every write refuses until the operator fixes the board, so list the
problems for them. Note `naming.iteration`, `review_label` and the board's
`iterations`.

## 2. Name the two iterations

- **Old:** the iteration the PM names, or else the active one. Read it with
  `get_iteration("<old>")` to get its state and dates.
  - **Planned:** it hasn't started, so it can't be closed yet. Stop and
    say so.
  - **Closed:** an earlier run closed it. Carry on; the close is then a
    no-op.
- **Next:** the iteration the PM names, or else the one after the old one
  by the board's naming. With `YYYYMM`, that's the following month, from
  its first day to its last: after `202610` comes `202611`, 2026-11-01 to
  2026-11-30. For any other pattern, ask the PM for the name and dates.
  If the next one is already in the board's `iterations`, read it with
  `get_iteration("<next>")` and use its dates as they are.

## 3. What's left, and what comes in

1. **Read the leftovers.** Call `find_items(iteration="<old>", limit=200)`.
   The default limit of 20 can cut a busy sprint short. If exactly the
   limit comes back, read again with a larger one.
2. **Keep what's unfinished:** every item whose state is neither `done`
   nor `cancelled`.
3. **Keep each task with its story or bug.** A task's `parent.id` is its
   parent's `id`.
   - If the parent is also unfinished, the task moves with it, in the
     same call.
   - If the parent is done or cancelled, or sits in another iteration,
     don't move the task alone. A tracker whose tasks are sub-tasks (Jira)
     doesn't reliably move a sub-task without its parent. List these tasks
     apart, and ask the PM whether each one should be finished, cancelled
     or left behind.
   - On Jira, a moved story takes all its tasks along, done ones too. Say
     so in the plan.
4. **Ask what comes in from the backlog.** To show candidates, call
   `find_items(state="todo", limit=50)` and leave out the items already in
   an iteration. The PM may name any other item by key; read it with
   `get_item("<key>")`.
   - If an item still has the review label, the PO hasn't reviewed it
     yet. Say so, and bring it in only if the PM confirms.
   - If the PM picks a task, bring its story or bug in with it.

## 4. Show the plan and wait for one yes

Show it in plain words:

- **Closing:** the old iteration's name and dates. On Plane, closing early
  moves its end date to yesterday.
- **Next:** its name and dates, whether it exists already or will be
  created, and whether it starts now (its dates cover today) or later.
- **Carried over:** each unfinished item by key, title and state, with its
  tasks under it.
- **From the backlog:** each pick by key and title.
- **Needs a decision:** the tasks from step 3 whose parent isn't moving.
- **Staying:** how many done and cancelled items stay in the old
  iteration.

Wait for one clear yes before any write. If the PM changes the plan, redo
step 3 as needed and show the plan again. The board's `confirm` mode
applies to filing items, not to this: always wait.

## 5. Roll over, in this order

The order is fixed. A Jira board has only one active sprint, so the old
one must close before the next one can start.

1. **Close.** Call `close_iteration("<old>")`. If it fails, stop, pass the
   message on, and say that nothing was written. Plane closes a cycle only
   from the day after it starts, and Jira closes only an active sprint.
2. **Find or create the next one.** Call
   `create_iteration("<next>", start="<first day>", end="<last day>")`, or
   give only the name when the next one already exists. An iteration whose
   dates cover today is active afterwards, which on Jira starts the sprint.
3. **Read the leftovers again.** Call
   `find_items(iteration="<old>", limit=200)`. If they differ from the plan
   because someone finished or added work in the meantime, show the
   difference and wait for another yes.
4. **Move.** Call `move_to_iteration(items=[…], iteration="<next>")` once,
   with the carried-over items, their tasks and the backlog picks.
5. **Check.** Call `find_items(iteration="<next>", limit=200)` and confirm
   that every moved key is there.

**If a write fails:**
- **Rate limit, edge wall, or tracker unreachable:** wait as the message
  says, then retry the same call.
- **Anything else:** stop and pass the message on. Running this skill again
  is safe. `close_iteration` returns an iteration that is already closed,
  `create_iteration` finds the one that exists, and the old iteration's
  leftovers show only what hasn't moved yet.

## 6. Report back

- Give the old iteration's name, now closed, and the next one's name and
  state.
- If the next one is still planned, say when it starts. Plane starts a
  cycle by its dates. On Jira, calling `create_iteration("<next>")` on or
  after its first day starts the sprint.
- List what moved, what stayed, and each decision the PM made.
