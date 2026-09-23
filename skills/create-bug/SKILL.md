---
name: create-bug
description: Files one bug from an intake record. It records what happens against what should happen, drafts Given/When/Then acceptance criteria for the fix with the requester, proposes where the bug goes, shows the preview, and commits only after a yes. Use after the intake skill decides a request describes something broken, or when a requester asks to report a bug or defect.
---

# Create a bug

One defect becomes one bug. This skill needs the intake record's shared
context: `id`, `problem` and `outcome`, plus `constraints`, `urgency` and
`related` when the requester gave them. If any of that is missing, run the
intake skill first. The tool names are the server's, and your host may add
a prefix.

## 1. What happens, and what should

Make sure the record says three things. Ask only for what's missing.

- **problem:** what the requester sees happen, where it happens, who runs
  into it and how often. For example: "Exporting a report with no rows
  shows an error page. Anyone exporting a quiet month hits it."
- **outcome:** what should happen instead, in their words.
- **How to make it happen:** the steps, in their words. These become the
  criteria below.

Don't ask for logs, versions or error codes the requester can't easily
give. Record what they saw. The team investigates.

## 2. Acceptance criteria

Draft 1–4 Given/When/Then criteria.

- **Given:** the situation where it breaks.
- **When:** the steps that trigger it.
- **Then:** the correct behavior.

Add a criterion that the normal case still works only when the fix could
plausibly break it. Show the criteria as a short numbered list in plain
words. Ask the requester to confirm, correct or add, and don't propose
until they agree.

## 3. Title

Name the broken behavior, not the fix, for example "Export Fails For
Empty Reports". Write it in the board's `naming.item_case` from
`describe_board()`.

## 4. Placement

- **parent:** the epic whose capability is broken, if the context
  provider found one. Name it by key and title. If none fits, leave it out.
- **feature:** the board feature the broken behavior belongs to, only
  when it clearly fits.
- **iteration:** leave it out, because the PM and PO schedule the fix.
  Set one only if the requester names an open iteration.
- **labels and assignees:** add none. The server adds the review label.

The record has one part, and that part has no name:

```json
{
  "id": "20260923-empty-report-export",
  "problem": "Exporting a report with no rows shows an error page instead of a file. Anyone exporting a quiet month runs into it, a few times a month.",
  "outcome": "Exporting an empty report gives me a file with just the column headers.",
  "urgency": "high",
  "related": ["AA-12"],
  "parts": [
    {
      "level": "bug",
      "title": "Export Fails For Empty Reports",
      "acceptance": [
        {"given": "a saved report with no rows", "when": "I choose Export > CSV", "then": "a .csv file with only the header row downloads"},
        {"given": "a saved report with rows", "when": "I export it", "then": "every row is in the file, as before"}
      ],
      "placement": {"parent": "AA-7"}
    }
  ]
}
```

## 5. Propose, confirm, commit

1. **Propose.** Call `propose_item(intake=<record>)`. It writes nothing. It
   checks the draft against the live board and returns a token, a preview
   and any warnings.
2. **If it fails,** the message says what to fix. Fix the record and
   propose again with the same id.
3. **Show the preview.** Include the level, title, parent, feature,
   iteration and description (problem, outcome and acceptance criteria).
   Say that the bug lands in Backlog, marked for the PO's review. Show
   every warning. For a suggested title, ask which title they want, and
   propose again if they pick the suggestion.
4. **If `existing` is set,** check whether this is the request's first
   proposal.
   - **First proposal:** another request already has this id. Make the id
     again with `-2` added (then `-3`) and propose again.
   - **Retry after an interrupted commit:** the bug already landed. Give
     the requester its key.
5. **Wait for a clear yes.** If they ask for changes, update the record
   and propose again.
6. **Commit.** Call `commit_item(token)`. If `describe_board()` reported
   `confirm = "never"`, commit right after proposing without asking, and
   still show what landed.
7. **Report back.** Give the key, say that it's in Backlog and marked for
   review, and say that the PO triages it next.

**If `commit_item` fails:**
- **Rate limit, edge wall, or tracker unreachable:** wait as the message
  says, then retry `commit_item` with the same token. It never creates a
  duplicate.
- **Expired or unknown token:** propose again with the same id, show the
  new preview, and wait for another yes.
