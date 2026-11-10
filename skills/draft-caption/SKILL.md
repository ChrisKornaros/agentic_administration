---
name: draft-caption
description: Drafts the description of a calendar item when that description is the finished text of a post, which another tool imports and publishes as written. It reads the board's caption rules (the most hashtags, the most characters, the one kind of link), drafts the caption, checks the whole description as it will land, and shows it with the counts. After one yes it writes the description to an existing item and reads it back, or hands the text to plan-cycle for a slot. Use when someone asks for a caption or the post text for an item on a board that states caption rules.
---

# Draft a caption

You work for the person who plans the board's posts. On a board like a
content calendar, an item's description is often the caption itself:
another tool imports it and publishes it as written. That tool refuses or
mangles text that breaks its rules, so the caption has to meet them before
it is filed. The board states those rules, and this skill drafts to them.
The tool names are the server's, and your host may add a prefix.

This skill changes one thing, an item's description. Nothing is deleted.

## 1. Read the board

Call `describe_board()` and keep the result.

If it returns `boards`, the server serves several. Use the board the
request names, by its name, its project or its description. If it names
none, list the boards with their descriptions and ask which one. Don't
choose one yourself. Then call `describe_board(board="<board>")` and keep
that result instead. Pass that `board` on every call, and name the board
in everything you show before a yes.

If `problems` is not empty, stop. Every write refuses until the operator
fixes the board, so list the problems for them.

Note `caption` and `templates`. `caption` holds the board's rules:

- `max_hashtags`: the most distinct hashtags the whole description may
  carry.
- `max_length`: the most characters, or null for no limit.
- `link_prefix`: the only kind of link the description may carry, or null
  when it may carry none.

If `caption` is null, the board states no caption rules. Say so and stop.
Don't make up limits, and don't borrow another board's.

## 2. Find what the caption is for

- **An item already on the board.** Read it with `get_item(ref="<key>")`
  and keep its title, dates and current description. If the request names
  no item, ask which one. Don't pick one from a search.
- **A slot the plan-cycle skill is drafting.** There is no item yet. Take
  the slot's template from `templates`: its `description` is a skeleton,
  and the caption goes where it says `{description}`. You write nothing
  here. You hand the text back, and plan-cycle files it with the slot.

## 3. Draft the caption

Ask what the post is, if the request doesn't say: the dish or subject,
the one thing a reader should take from it, and the link, if it has one.
Write the caption from that, in the person's own words where they gave
any. Don't invent facts, such as times, quantities or names.

Shape it the way it will be read as plain text:

- **The body is plain paragraphs,** with a blank line between them. No
  headings, no bullet or numbered lists, no block quotes, no code fences
  and no bold or italic markers. The board turns those into formatting,
  and the tool that imports the text sees none of the markers.
- **The link, if there is one, goes on a line of its own,** once, as the
  bare URL, with a line break after it. It starts with `link_prefix`, has
  no spaces (write a space in a path as `%20`) and no `#` part, since
  that would read as a hashtag. Never write it as `[text](url)`: the board
  stores the link's label, and a reader of the text sees no address.
- **The hashtags go at the end, on a line of their own,** never inside a
  sentence.

## 4. Check the whole description as it will land

Check what the item's description will be once written, not the caption
alone:

- For an existing item, that is the whole text you will send. An update
  replaces the description, and the template is not applied again. If the
  item's current description ends with hashtags that its template added,
  keep them or drop them on purpose, and count the ones you keep.
- For a slot, put your text into the template's skeleton where it says
  `{description}`. Whatever the skeleton adds around it counts, such as
  hashtags of its own.

Then check each rule:

1. **Hashtags.** A hashtag is `#` followed directly by letters, digits or
   underscores, anywhere in the text. `#1` is one. Count the distinct
   ones, without regard to case, so `#Bread` and `#bread` are one. The
   count must not pass `max_hashtags`. If it does, say which tags are
   there and ask which to drop. Never file an over-limit description in
   the hope that something later trims it.
2. **The link.** At most one URL in the whole text. It starts with
   `link_prefix`, sits on its own line and is written bare. If
   `link_prefix` is null, the text carries no URL.
3. **Plain text.** No line starts with `#` and a space, `- `, `* `, `> `
   or a number and a dot, and the text has no `](`.
4. **Length.** The character count is within `max_length`, when the board
   sets one.

When the person's own text can't meet a rule without a choice that is
theirs, say so plainly and ask. For example, six hashtags they all want
on a board that allows five: name the six and ask which one goes.

**An example,** on a recipe board whose rules are `max_hashtags` 5,
`max_length` 2200 and `link_prefix` `https://example.com/recipes/`, for a
slot whose template skeleton is `{description}`, a blank line, then
`#recipes #homecooking`. The text handed back for the slot:

```text
Weeknight ragu that tastes like Sunday. Brown the beef hard, add the tomatoes, and let it go low for forty minutes while the pasta water comes up.

The full recipe, with the timings:
https://example.com/recipes/weeknight-ragu

#ragu #pasta #weeknightdinner
```

The description lands with the skeleton's line after it, so it carries
five distinct hashtags: three from the caption and two from the template.
A fourth tag in the caption would make six, one over the limit.

## 5. Show it and wait for one yes

Show:

- The board, by name, and the item's key and title, or the slot's part
  name and day.
- The exact description as it will land, in a code block so nothing is
  reformatted.
- The hashtag count against `max_hashtags`, with the tags listed.
- The link, or that there is none.
- The length against `max_length`.
- For an existing item, what the description is now, so they see what is
  replaced.

Wait for one clear yes before any write. If they change anything, draft
again, check again and show it again. The board's `confirm` mode applies
to filing items, not to this: always wait.

## 6. Write it and read it back

**For a slot,** hand the text back to plan-cycle as that slot's
`description` and stop. You write nothing.

**For an existing item:**

1. Call `update_item(ref="<key>", description="<the whole description>")`.
   Send the description and nothing else: not the title, state, dates,
   labels, parent, feature or fields.
2. Read it back with `get_item(ref="<key>")` and run the checks in step 4
   again on the description the board returned. The board stores rich
   text, so compare what a reader of the text gets: the same paragraphs,
   the same link on its own line, the same hashtags.
3. If the read-back breaks a rule or lost something, say exactly what
   differs. Don't write again without asking.

**If the write fails:**
- **Rate limit, edge wall, or tracker unreachable:** wait as the message
  says, then retry the same call.
- **Anything else:** stop, pass the message on, and say that the item's
  description is unchanged.

## 7. Report back

- Give the item's key and title, and that its description is now the
  caption, or the slot the text went to.
- Give the hashtag count, the link and the length as read back.
- Say what differs from what was shown, or that it matches.
