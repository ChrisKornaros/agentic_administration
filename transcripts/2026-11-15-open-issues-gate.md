# Open issues in a rollover plan: the gate (2026-11-15)

The question: with the `issues` server configured, does `plan-sprint`
show the PM an open issue that no board item covers, and change nothing
doing it? **PASS.** The plan listed the one hand-filed issue under "Open
issues with no board item", with its number, title and URL, and no other.
The PM answered no and nothing was written.

This was **author-run**: Chris played the PM on his own board. This is a
summary. The items' and the issue's text stay out of git; the raw session
is in `transcripts/raw/`, which is gitignored.

## Setup

- **Session:** Claude Code 2.1.323, started from an empty directory with
  the README's flags plus `find_open_issues` pre-allowed, on Fable 5.2
  (`claude-fable-5-2`). The plugin was loaded from the branch
  `feat/open-issues-server`.
- **Board:** Plane, a real software board with one active monthly cycle
  of 28 items, 27 of them done.
- **Code host:** a private repository with one open issue, filed by hand
  for this run with no board key in its text. The token is a
  fine-grained one with read access to that repository's issues only,
  from Bitwarden through `server/secrets.py`.
- **The request:** a rollover from the active cycle into the next month.

## What happened

- The skill read the board, the old cycle (twice: its state, then its
  items), the todo backlog and then the open issues, with
  `find_open_issues(limit=50)`.
- The issue named no key, so the skill searched the board by words from
  its title, twice (`limit=10`, then `limit=5`). Neither search found an
  item, so no `get_item` followed.
- The plan showed the closing cycle, the next one, the one carried item,
  an empty backlog pick, and the issue in its own section, with the line
  that the plan does not change it and that it goes through intake to be
  planned.
- Calls made: `describe_board`, `get_iteration`, `find_items` (four),
  `find_open_issues`. No write tool was called.

## Checks

| Check | Result |
|---|---|
| The server, called directly over stdio before the session, returns the one open issue with empty `item_keys` | ✅ |
| The same list as the code host's own (`gh issue list`) | ✅ one issue |
| The plan names the issue under "Open issues with no board item" and no other | ✅ |
| No write before the PM's answer, and none after a no | ✅ |
| The skill's text names no code host (`grep -ci github skills/plan-sprint/SKILL.md`) | ✅ 0 |

## Findings

1. **The first title search used `limit=10`; the skill says `limit=5`.**
   Harmless here. It is the kind of drift the skill's fixed wording is
   meant to prevent, so it is worth watching on the next run.
2. **Not exercised:** an issue that names a key (the *on the board*
   group), an issue tied only by a link (the *linked* group, which needs
   the `get_item` reads), more issues than the limit, and a rate-limited
   answer.
