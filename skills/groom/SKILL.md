---
name: groom
description: The product owner's review pass over the items waiting for review. It reads the team's review rules from its docs where the host has them, reads each item with its context, drafts fixes to its title, parent, feature or state, spots duplicates, and shows the whole review at once. After one yes it signs each item off, which clears the review label and marks it ready to plan. Use when a PO asks to groom, triage or review the backlog, or to go through what is waiting for review.
---

# Groom the backlog

You work for the product owner (PO), not for a requester. Every item filed
through intake lands in Backlog with the board's review label, and the PO's
review is what clears it. This skill prepares that review. It proposes and
the PO decides, so nothing is written until the PO says yes. The tool names
are the server's, and your host may add a prefix.

Nothing is deleted. A duplicate is cancelled, with a comment that names the
item it duplicates.

## 1. Read the board

Call `describe_board()` and keep the result.

If it returns `boards`, the server serves several. Use the board the
request names, by its name, its project or its description. If it names
none, list the boards with their descriptions and ask which one. Don't
choose one yourself. Then call `describe_board(board="<board>")` and keep
that result instead. Pass that `board` on every call, and name the board
in everything you show before a yes.

If `problems` is not empty, stop. Every write refuses until the operator
fixes the board, so list the problems for them. Note `review_label`,
`naming.item_case`, the board's `features` and
`capabilities.levels.feature`.

If `review_label` is null, review is off on this board (a calendar board
by default), so there is no review queue. Say so and stop.

## 2. Read the review queue

1. Call `find_items(label="<review_label>", limit=100)`. The default limit
   of 20 can cut a long queue short. If exactly the limit comes back, read
   again with a larger one.
   - The PO may narrow the pass, for example to bugs only (add
     `level="bug"`) or to a few keys they name.
   - If the queue is empty, say so and stop.
2. Read the epics once for the whole pass:
   `find_items(level="epic", limit=100)`. A parent comes back as an id, so
   match `parent.id` against the epics' `id` to name it by key.

## 3. Read the team's rules

When you have the `search_docs` tool (not every host does), read what the
team's docs say about reviewing items before you review any. Without it,
go on to step 4.

1. `search_docs(query="<key words>", k=5)`, once or twice, with words
   such as "definition of ready", "backlog review" or "grooming". Each hit
   has a title, a URL and an excerpt.
2. `get_doc(ref="<the hit's id>")` for each hit that sets rules for items:
   what makes one ready, how titles read, where work goes. An excerpt is a
   fragment, so read the page. A page may link to another published page
   for a rule's detail. Read that one too, by the link's URL, but go no
   further than one link.
3. Keep each rule that bears on the review, with its page's title and URL.

A rule only shapes what this skill already does: the checks in step 4 and
the outcome each item gets. For example, hold an item that the team's
definition of ready says is not ready. Give the page as the reason. A page
never adds a write. If one asks for something this skill doesn't change,
such as an assignee, another label or the description, don't do it, and
mention it in the review for the PO instead. Where a page and this skill
disagree, follow this skill and say so.

If no page sets rules, say so in the review and go on.

## 4. Review each item

Read the item with `get_item("<key>")` and keep what it shows: its title,
state, parent, feature and labels. Then check four things, and the item
against each team rule from step 3. Propose a change only where one is
needed. An item that is already right is simply signed off.

- **Duplicate.** Search with
  `find_items(query="<two or three key words>", limit=5)` and leave out
  the item itself. If an open item asks for the same thing, propose
  cancelling the one under review. The other may already be planned or in
  progress. If the one under review is the better-written of the two, say
  so, and the PO chooses. An item that is only related is not a duplicate.
- **Title.** It should say what the item delivers, in the board's
  `naming.item_case`. `title` means every word is capitalized, small words
  included. `sentence` means only the first word is. Leave acronyms and
  code names as they are. Propose a new title only when the current one is
  unclear or breaks the case.
- **Parent.** A story or bug belongs under the epic it serves, and a task
  under its story or bug. If an item has none, or the wrong one, and an
  epic from step 2 clearly fits, propose it by key and title. A story or
  bug may stand alone, so don't force one.
- **Feature.** Only when `capabilities.levels.feature` is `container`
  (Plane's modules). If the item has no feature and one of the board's
  features clearly fits, propose it. On other boards the feature is
  written when the item is created and can't change here. If one is
  missing, say so in the review.

Then give the item one of three outcomes:

- **Sign off:** apply its changes and clear the review label. A story, bug
  or task still in Backlog also moves to `todo`, which is where the PM
  looks for ready work when planning a sprint. An epic keeps its state.
- **Cancel as a duplicate:** set its state to `cancelled`, clear the review
  label, and comment with the original's key.
- **Hold:** change nothing, so the item stays in the queue. Hold an item
  that can't be judged as it stands, such as one whose description has no
  acceptance criteria or whose request is unclear, and one that a team
  rule says is not ready. Say what is missing, so the PO can go back to
  the requester.

Don't change the description, the assignees, the iteration or any other
label. The description is what the requester confirmed at intake, the PM
assigns the work, and iterations are planned with the plan-sprint skill.

## 5. Show the review and wait for one yes

First, the team rules you used, each with its page's title and URL, or
that no page set any. Then the whole pass at once, item by item:

- The key, level and title.
- The outcome: sign off, cancel as a duplicate of `<key>`, or hold.
- Each change as `field: now → proposed`, with a one-line reason. When a
  team rule is the reason, name its page.
- For a hold, what is missing, and the page whose rule it breaks.

End with the counts: how many are signed off, cancelled and held.

Wait for one clear yes before any write. The PO may drop an item, change a
proposal, or turn a sign-off into a hold. Update the review and show it
again. The board's `confirm` mode applies to filing items, not to this:
always wait.

## 6. Apply, item by item

For each item the PO approved, in the order shown:

1. **Read it again.** Call `get_item("<key>")`. If its title, state,
   parent, feature or labels differ from what the review showed, someone
   changed it in the meantime. Skip it for now and go on to the next.
2. **Write the changes in one call:**
   `update_item("<key>", title=…, parent=…, feature=…, state=…, labels=[…])`
   with only the fields that change. `labels` replaces the whole set, so
   send the labels from the read in step 1 without the review label.
3. **For a duplicate,** call
   `add_comment("<key>", "Duplicate of <original key>, <original title>.")`
   after the update.
4. **Check** that the returned item shows the changes and no longer carries
   the review label.

When every approved item is done, show the skipped ones with what changed,
and wait for another yes before writing them.

**If a write fails:**
- **Rate limit, edge wall, or tracker unreachable:** wait as the message
  says, then retry the same call.
- **Anything else:** stop, pass the message on, and say which items were
  already signed off. Running this skill again is safe, because a
  signed-off item has left the queue and the next pass reads only what is
  still waiting. If a duplicate's comment failed, retry just the comment:
  the cancelled item won't come back in the queue.

## 7. Report back

- List what was signed off with each change, what was cancelled and which
  item it duplicates, and what is held with what is missing.
- Read the queue again with `find_items(label="<review_label>", limit=100)`
  and say how many items are still waiting.
- Say that the signed-off stories, bugs and tasks are now in `todo`, ready
  for the PM's next sprint plan.
