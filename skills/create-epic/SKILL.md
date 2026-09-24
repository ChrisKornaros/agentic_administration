---
name: create-epic
description: Splits one intake request into an epic and the stories under it. Each story gets its own Given/When/Then acceptance criteria. It shows the whole split, takes one yes, then files the epic first and each story under it. Use after the intake skill decides a request is several pieces of work or more than one iteration, or when a requester asks for an epic or a breakdown.
---

# Create an epic and its stories

One request becomes an epic plus the stories under it. This skill needs the
intake record's shared context: `id`, `problem` and `outcome`, plus
`constraints`, `urgency` and `related` when the requester gave them. If any
of that is missing, run the intake skill first. The tool names are the
server's, and your host may add a prefix.

## 1. Decompose

Build the split from epics and stories only. Features are optional
attachments, and tasks are the team's to add later.

- **The epic** names the goal ("Report Exports"). Its part is named
  `epic`, it has no parent, and it needs no acceptance criteria.
- **Each story** is one piece of the outcome that the requester would
  notice on its own. It fits in one iteration and can ship without the
  others where possible. Aim for 2–6 stories. A story is never a pure
  technical step such as "set up the database": fold that step into the
  story that needs it.
- **If a piece is really a defect,** make it a bug part in the same
  split. It is placed like a story.
- **If only one story is left,** it isn't an epic. Use create-story.

Give every part a short name made of letters, digits, `.`, `_` and `-`
(`csv`, `pdf`, `schedule`). Its external id becomes `<id>/<name>`, and a
story points at the epic with `placement.parent = "#epic"`.

## 2. Acceptance criteria, titles, placement

- **Criteria:** for each story, draft 2–5 Given/When/Then criteria from
  its slice of the outcome. Given is the situation, When is what the
  person does, and Then is what they see or get. Each covers one
  behavior the requester could check, with no implementation detail.
- **Titles:** write every title in the board's `naming.item_case` from
  `describe_board()`.
- **feature:** for each story, one of the board's features only when it
  clearly fits.
- **iteration:** leave it out, because the PM and PO plan iterations.
- **labels and assignees:** add none. The server adds the review label.

List the epic first. A story's `#epic` parent can only be found once the
epic has been committed.

```json
{
  "id": "20260923-report-exports",
  "problem": "Our finance team re-types report totals into spreadsheets and slides by hand every month.",
  "outcome": "I can get any saved report out as a spreadsheet file or a PDF, on demand or on a schedule.",
  "constraints": ["no new paid service"],
  "urgency": "medium",
  "parts": [
    {"part": "epic", "level": "epic", "title": "Report Exports"},
    {
      "part": "csv", "level": "story", "title": "Export Reports As CSV",
      "acceptance": [
        {"given": "a saved report", "when": "I choose Export > CSV", "then": "a .csv file with every row downloads"}
      ],
      "placement": {"parent": "#epic", "feature": "Reporting"}
    },
    {
      "part": "pdf", "level": "story", "title": "Export Reports As PDF",
      "acceptance": [
        {"given": "a saved report", "when": "I choose Export > PDF", "then": "a PDF that matches the on-screen report downloads"}
      ],
      "placement": {"parent": "#epic", "feature": "Reporting"}
    },
    {
      "part": "schedule", "level": "story", "title": "Email A Report Export On A Schedule",
      "acceptance": [
        {"given": "a saved report with a monthly schedule", "when": "the first of the month arrives", "then": "its owner receives the export by email"},
        {"given": "a scheduled report", "when": "I turn the schedule off", "then": "no further emails are sent"}
      ],
      "placement": {"parent": "#epic", "feature": "Reporting"}
    }
  ]
}
```

## 3. One yes for the whole split

Show the requester the whole split from the record: the epic's title, then
each story's title, acceptance criteria and feature. Say that it lands as
that many items in Backlog, each marked for the PO's review. If they ask
for changes, edit the record and show it again. One clear yes covers the
whole split.

If `describe_board()` reported `confirm = "never"`, skip the yes. Still
show the split, then file it.

## 4. File it: the epic first, then each story

1. **The epic.** Call `propose_item(intake=<record>, part="epic")`. It
   writes nothing, checks the draft against the live board, and returns a
   token and a preview.
2. **Compare the preview with what the requester saw.** It matches when
   the call didn't fail, `warnings` is empty and `existing` is null. If it
   matches, call `commit_item(token)` right away with no second question,
   because the description is rendered from the same record they
   confirmed.
3. **Each story, in record order.** Call
   `propose_item(intake=<record>, part="<name>")` and compare in the same
   way. If it matches, call `commit_item(token)`.
4. **When a preview differs, stop on that item and ask about it alone.**
   - **Failure:** fix the record and say what changed.
   - **Suggested title:** ask which title they want.
   - **`existing` on the request's first run:** another request already
     has this id. Make the id again with `-2` added and start again from
     the epic.
   - **`existing` on a retry:** that part already landed. Skip it and
     continue.

   Propose that item again, and once they agree, continue with the rest.
   With `confirm = "never"`, commit through warnings and report them.
   A failure still has to be fixed before that item can land.
5. **Report back.** List every key, epic first, and say that the PO
   reviews them next. If something didn't land, say which parts did and
   which didn't. Running this step again proposes the rest, and the parts
   that already landed come back as `existing`.

**If `commit_item` fails:**
- **Rate limit, edge wall, or tracker unreachable:** wait as the message
  says, then retry `commit_item` with the same token. It never creates a
  duplicate.
- **Expired or unknown token:** propose that part again. Commit without
  asking only if the new preview still matches.
