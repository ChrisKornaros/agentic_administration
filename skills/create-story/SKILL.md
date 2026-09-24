---
name: create-story
description: Files one story from an intake record. It drafts Given/When/Then acceptance criteria with the requester, proposes where the story goes, shows the preview, and commits only after a yes. Use after the intake skill decides a request is one new capability or change, or when a requester asks to file a single story or feature request.
---

# Create a story

One request becomes one story. This skill needs the intake record's shared
context: `id`, `problem` and `outcome`, plus `constraints`, `urgency` and
`related` when the requester gave them. If any of that is missing, run the
intake skill first. The tool names are the server's, and your host may add
a prefix.

## 1. Acceptance criteria

Draft 2–5 Given/When/Then criteria from the outcome.

- **Given:** the starting situation.
- **When:** what the person does.
- **Then:** what they see or get.

Each criterion covers one behavior that the requester could check
themselves, with no implementation detail. Add a failure case only when
the outcome implies one, such as an empty list or no permission. Show the
criteria as a short numbered list in plain words. Ask the requester to
confirm, correct or add, and don't propose until they agree.

## 2. Title

Name the capability briefly, for example "Export Reports As CSV". Write it
in the board's `naming.item_case` from `describe_board()`. `title` means
every word is capitalized, small words included. `sentence` means only
the first word is capitalized. Leave acronyms and code names as they are.

## 3. Placement

- **parent:** the epic this belongs to, if the context provider found one
  that fits. Name it by key and title. If none fits, leave it out, because
  a story may stand alone.
- **feature:** one of the board's features, only when it clearly fits.
  Otherwise leave it out and the PO sets it.
- **iteration:** leave it out, because the PM and PO plan iterations after
  review. Set one only if the requester names an open iteration.
- **labels and assignees:** add none. The server adds the review label,
  and the PM assigns the work.

The record has one part, and that part has no name:

```json
{
  "id": "20260923-export-reports-csv",
  "problem": "Our finance team re-types report totals into a spreadsheet by hand every month.",
  "outcome": "I can download any saved report as a file my spreadsheet opens.",
  "constraints": ["no new paid service"],
  "urgency": "medium",
  "related": ["AA-12"],
  "parts": [
    {
      "level": "story",
      "title": "Export Reports As CSV",
      "acceptance": [
        {"given": "a saved report", "when": "I choose Export > CSV", "then": "a .csv file with every row downloads"},
        {"given": "a report with no rows", "when": "I export it", "then": "the file holds only the column headers"}
      ],
      "placement": {"parent": "AA-7", "feature": "Reporting"}
    }
  ]
}
```

## 4. Propose, confirm, commit

1. **Propose.** Call `propose_item(intake=<record>)`. It writes nothing. It
   checks the draft against the live board and returns a token, a preview
   and any warnings.
2. **If it fails,** the message says what to fix, such as an unknown
   feature or an epic key that doesn't exist. Fix the record and propose
   again with the same id.
3. **Show the preview.** Include the level, title, parent, feature,
   iteration and description (problem, outcome and acceptance criteria).
   Say that the story lands in Backlog, marked for the PO's review. Show
   every warning. For a suggested title, ask which title they want, and
   propose again if they pick the suggestion.
4. **If `existing` is set,** check whether this is the request's first
   proposal.
   - **First proposal:** another request already has this id. Make the id
     again with `-2` added (then `-3`) and propose again.
   - **Retry after an interrupted commit:** the story already landed. Give
     the requester its key.
5. **Wait for a clear yes.** If they ask for changes, update the record
   and propose again. The old token is simply dropped.
6. **Commit.** Call `commit_item(token)`. If `describe_board()` reported
   `confirm = "never"`, commit right after proposing without asking, and
   still show what landed.
7. **Report back.** Give the key, say that it's in Backlog and marked for
   review, and say that the PO reviews it next.

**If `commit_item` fails:**
- **Rate limit, edge wall, or tracker unreachable:** wait as the message
  says, then retry `commit_item` with the same token. It never creates a
  duplicate.
- **Expired or unknown token:** propose again with the same id, show the
  new preview, and wait for another yes.
