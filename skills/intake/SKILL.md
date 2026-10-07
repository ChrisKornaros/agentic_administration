---
name: intake
description: Turns a requester's plain-language ask ("can we get…", "X is broken") into a complete intake record by asking, then hands it to create-story, create-bug or create-epic to file on the board. Use when someone wants work added to the backlog and hasn't yet said the problem, the outcome and how to tell it's done.
---

# Intake

You are the requester's scribe, not the product owner. The requester gives
you a sentence or two. You ask until the intake record's shared context is
complete, then a create skill files the item. The record's shape is the
`intake` argument of the `propose_item` tool.

The tool names here are the server's. Your host may add a prefix (for
example `mcp__agentic-administration__find_items`).

## 1. Read the board once

Call `describe_board()` at the start and keep the result for the rest of
the conversation. From it, note:

- `problems`: if this is not empty, stop. Nothing can be filed until the
  operator fixes the board. Tell the requester, and list the problems for
  the operator.
- `confirm`, `naming.item_case`, the board's features (`containers`) and
  its iterations.
- `review_label`: null means review is off on this board, so nothing
  filed is marked for review.
- `capabilities.levels.bug`: `absent` means the board has no bug level
  (a calendar board), so a defect is filed as a story.

## 2. Problem and outcome first

Ask only for what's missing, at most two questions per turn, in plain
words. Don't use tracker terms (epic, story) unless the requester does.

- **problem**: the need, and who runs into it. For example: "What's
  missing, slow or broken today, and who notices?"
- **outcome**: what done looks like, in their words. For example: "Once
  this is done, what can you do that you can't do now?"

Record their words, lightly edited. Don't add facts they didn't give. If
they describe a solution ("add a button"), ask what it's for. Keep the
solution only as a constraint, and only if they insist on it.

Keep their voice. Write the problem and outcome as they would say them,
with "I", "we" or "our team", the same voice as the acceptance criteria.
Don't name the requester, or anyone they didn't name. A name you know from
somewhere else is a fact they didn't give.

Then ask one optional question covering both **constraints** (musts,
must-nots, dates, dependencies) and **urgency** (low, medium or high, as
their gut feel; the PM orders the backlog). "Not sure" is fine. Leave the
field empty.

## 3. Context provider: what already exists

Look for related work, and for docs that already answer the ask, before
proposing placement. All retrieval happens in this step. To use a
different provider, change this step and nothing else.

- **Input:** a short query taken from the problem and outcome (2–4 key
  words).
- **Output:** candidate items, each with a key, title and level, and doc
  pages, each with a title and URL.
- **The board's own search,** always:
  - `find_items(query="<key words>", limit=5)`, once or twice. Keep
    `limit` small, because each hit is read one at a time and 20 hits can
    take a minute on a throttled tracker.
  - `find_items(level="epic")`: the epics a story or bug could go under.
- **The team's docs,** when you have the `search_docs` tool (not every
  host does):
  - `search_docs(query="<key words>", k=5)`, once or twice. Each hit has a
    title, a URL and an excerpt.
  - `get_doc(ref="<the hit's id>")` for a hit that looks like it answers
    the ask. An excerpt is a fragment, so read the page before you tell
    the requester anything from it.
- **Another provider** (a knowledge graph): swap in its tool here, and
  have it return the same key, title and level.

Bring a find up with the requester only when it matters. For example:
"AA-12, Export Reports, already exists. Is this part of it, or separate?"
Then:

- Items they confirm as related go into `related` as keys. Something they
  mention that you can't find goes in as their own words.
- A fitting epic becomes the create skill's placement candidate.
- If an item already is this request, say so. Offer to add their details
  to it with `add_comment(ref, body)`, and do that only after they say
  yes. File a new item only if they want one.
- If a doc already answers the ask (the thing exists, or it says how to
  do it), tell them what the page says, in a sentence or two and in its
  own terms, with its URL. Add nothing it doesn't say. Then ask whether
  that settles it. File an item only if they still want one. A page
  they confirm as related goes into `related` as its URL.

## 4. Decide the shape

- **Something that worked, or should work, but doesn't:** a bug. Use
  **create-bug**. On a board with no bug level, it's a story: use
  **create-story**.
- **One new capability or change a team could finish in one iteration:**
  a story. Use **create-story**.
- **Several pieces the requester would each notice, or more than one
  iteration of work:** an epic with its stories. Use **create-epic**.

Between a story and an epic, prefer the story, because the PO can promote
it later. Tell the requester in plain words, for example "I'll file this
as one request" or "this looks like three pieces of work".

## 5. Make the id

The id is `YYYYMMDD-<slug>`: today's date and 2–4 lowercase words from the
outcome, joined by hyphens, for example `20260923-export-reports-csv`. Use
letters, digits, `.`, `_` and `-`, up to 64 characters. Make it once per
request and keep it. Every re-proposal and retry of this request reuses
it, which is what stops a retry from filing a duplicate.

Continue with the create skill you chose. Carry the record so far: `id`,
`problem`, `outcome`, `constraints`, `urgency` and `related`.
