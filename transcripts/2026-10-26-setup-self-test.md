# Setup from a fresh directory: the author's self-test (2026-10-26)

The question: can a coding agent with no context take this repo's URL and
"Please set this up for my organization", follow [SETUP.md](../SETUP.md),
and leave a working backlog chat on a board the team already uses, while
the person only answers questions and says yes? **PASS.** The agent found
the guide from the README, asked its questions in one message, never
asked for or printed a token, fitted the config and wrote the launcher.
The chat then read the board, groomed one item and filed one new item,
each after a yes.

This was **author-run, agent-led**: Chris played the admin, and he knows
the answers. It is not the stranger's gate (Phase 7 step 5), which stays
open for a friend on the public repo and a free Jira site. This is a
summary. The items' text is board content, so it stays out of git; the raw
sessions are in `transcripts/raw/`, which is gitignored.

## Setup

- **Setup session:** Claude Code 2.1.310 under a fresh `CLAUDE_CONFIG_DIR`
  (no global `CLAUDE.md`, memory or hooks), started in an empty directory
  outside the vault. Opus 5.5 (`claude-opus-5-5`). Permission mode `auto`,
  the fresh config's default, so no command waited for approval.
- **Chat session:** Claude Code 2.1.311, started by the launcher the setup
  agent wrote, from an empty directory, with the README's flags (recorded
  as `default`). It ran under Chris's normal Claude Code config, so his
  global `CLAUDE.md` was in its context (finding 4).
- **Board:** Jira, throwaway project `AGADM`, board 2; the classic token
  from Bitwarden through `server/secrets.py`. No docs.
- **The guide:** `main` at `b0aedc1`, with PR #46's SETUP.md.

## The setup session

1. It cloned the repo, read the README, found SETUP.md, and asked step 1's
   questions in one message, each with its default.
2. Chris answered as an admin: Jira and a link to the project's issues
   (not its board), Premium, a board already in use, software, Claude
   Code, the Bitwarden item and session file, `needs-review`, `YYYYMM`,
   title case, no docs, and "clone into /tmp".
3. It installed with `uv sync`, ran the offline suite (pass), and checked
   the session file's mode.
4. It wrote the config from the Jira template. The link had no
   `/boards/`, so the template's `board_id = 1` stayed, and `describe`
   refused it before any write: board 1 is a simple board, and sprints need
   a Scrum board.
5. To find the Scrum board, it wrote its own read-only REST script, which
   took the token through `server/secrets.py`. It found board 2 (finding
   1). `describe` then ended with `config fits the board.`
6. Before handing over, it passed on the guide's notes for a board already
   in use: a shared workflow scheme, To Do work counting as ready, Jira's
   own Task type reading back as a story. It added that `describe` doesn't
   check transitions or board columns.
7. It wrote the launcher. The launcher holds no token: it sets the
   Bitwarden item's variables, reads the session file, `cd`s into an empty
   directory and runs the README's command unchanged. Then it handed over.
8. After the chat, it read AGADM-15 and AGADM-19 back with another script
   of its own. It noticed AGADM-15 was an edit, not the checklist's new
   item, and closed the checklist only on AGADM-19.

15 shell calls. None ran `conformance`, `bw get` or `bw list`. A scan of
both raw sessions found no token-shaped string and no Bitwarden session
key.

## The chat session

| # | Chris typed | What happened |
|---|---|---|
| 1 | "What's on the board" | `describe_board` and `find_items`: 18 items, its sprints, and what waits for review |
| 2 | Why one story waits for review | It explained the review label and pointed at the story's two untestable criteria |
| 3 | Fix the criteria and move it to To Do | `groom`: one review, one yes, a fresh `get_item`, then `update_item` (the criteria, the state, the label cleared) and a read of the queue, now empty. It said it had no docs tool, so it used the skill's own checks |
| 4 | Add one more test story | `intake` → `create-story`: `propose_item`, one yes, then `commit_item` → AGADM-19 |

Tools: `describe_board` 2, `find_items` 7, `get_item` 2, `update_item` 1,
`propose_item` 1, `commit_item` 1, `Skill` 3.

## Read-back

Through the adapter, read-only, apart from both sessions:

- **AGADM-15:** story, `todo`, no labels. It is the groomed item.
- **AGADM-19:** story, `backlog`, `needs-review`, xid
  `20261026-review-queue-signoff`. On a board already in use, the create
  and the move into Backlog worked.

## Findings

| # | Finding | What follows |
|---|---|---|
| 1 | Twice the agent wrote its own Jira REST script: to list the project's Scrum boards, and to read items back. Each script took the token through `server/secrets.py` and printed nothing secret, but writing an API client is not the setup's job. The cause is a gap: `describe` names a wrong board's type but not the project's Scrum boards, and no read-back command exists | SETUP.md's agent rules now say not to call the tracker's API directly, but to ask the person. Follow-ups: `describe` lists the project's Scrum boards when `board_id` is wrong, and a read-only command reads one item back |
| 2 | A board link was the first thing asked for, but the person gave an issues link, and the template's `board_id` slipped through | `describe` caught it before any write. Finding 1's follow-up covers it |
| 3 | The setup ran in `auto` mode, the fresh config's default, so nothing waited for approval | Record only. The guide can't set the host's mode. Every command was a read or a local file, and the board saw no write from the setup |
| 4 | The chat ran under the author's normal config, since the launcher doesn't set `CLAUDE_CONFIG_DIR` and the test step was missed. The chat's context held his global `CLAUDE.md`, but nothing in the chat referred to it | Record only. A team member's chat runs under their own config. The friend's test removes this |
| 5 | The guide's notes for a board already in use reached the person before anything changed | The rehearsal's fixes (PR #46) work on a real board |
