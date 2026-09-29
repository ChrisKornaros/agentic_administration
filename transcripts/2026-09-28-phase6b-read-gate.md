# Phase 6b read gate: an agent answers from the docs (2026-09-28)

The gate, from AOR roadmap/14 §9 Phase 6b: *an agent answers from the docs
through `search_docs`.* **PASS**, on the second of two sessions. In the
first, the docs had nothing on the request, so the agent searched them,
said so, and filed a story. The overview page it asked for was then
published, and the same request, asked again, was answered from that page
with nothing filed.

This is a summary. The requests and the items' text are board content, so
they stay out of git. The raw sessions are in `transcripts/raw/`, which is
gitignored.

## Setup

- **Host:** Claude Code 2.1.284, with the repo loaded as a plugin from an
  empty directory. The command was the README's (`--tools Skill`, the
  framing line, the reads pre-allowed), with
  `ENABLE_CLAUDEAI_MCP_SERVERS=false`.
- **Model:** Opus 5.5 (`claude-opus-5-5`), as in the Phase 3 and 4 gates.
- **Servers:** `board` on Jira, throwaway project `AGADM`
  (`confirm = "always"`, `item_case = "title"`), and `knowledge` on
  Confluence, throwaway space `AGKB`. Both use the same classic token from
  Bitwarden. Session 1 read the docs through a config scoped to the
  conformance run's label (`md-published-20260928`), whose pages cover
  only a setup step. Session 2's config used `md-published` under a fresh
  parent page, "Team Docs".
- **Requester:** Chris, typing a plain request for an overview of the
  project. Neither session mentioned docs, Confluence or tools.

## Session 1: nothing in the docs

| Step | What happened |
|---|---|
| Start | the intake skill, then `describe_board` once |
| Questions | two, then the optional constraints-and-urgency question, which came after the search |
| Context step | three `find_items` (two key-word searches and the epics) and two `search_docs` ("project overview", "purpose introduction"), all in intake's step 3. Both searches came back empty |
| Told the requester | that it had checked the board and the team's docs and found nothing close, so this would be new |
| Filed | AGADM-6, a story, after the criteria were confirmed, the preview shown and a yes |

The session ran in Claude Code's **auto** permission mode, Chris's own
default. `commit_item` went through without a permission prompt, so the
skill's yes was the only guard (finding 2).

## Session 2: the page answers the request

Between the sessions, a short overview page was published to `AGKB` with
`python -m knowledge publish`: a dry run, then one page and two writes. A
second run wrote nothing. `search_docs("project overview")` found the page
7 s after the publish.

| Step | What happened |
|---|---|
| Start | the intake skill, then `describe_board` once |
| Questions | two. The optional question was skipped, because the context step settled the request first |
| Context step | three `find_items` (found AGADM-6 from session 1, and the epics) and two `search_docs` ("overview agentic tooling", "testing purpose"). Both found the page |
| Read | `get_doc` on the page's id, before telling the requester anything from it |
| Told the requester | what the page says, in its own terms and with its link, adding nothing it doesn't say. It also said AGADM-6 already asks for the same thing, so nothing new would be filed, and asked whether the page covered it |
| Afterwards | offered a comment on AGADM-6 linking the page, only on a yes. The requester said the page covered it without asking for the comment, so none was posted |

No write tool was called. The session ran with `--permission-mode manual`,
recorded as `default`.

## Read back afterwards

A read-only `find_items(query="overview")` on `AGADM` found only AGADM-6:
a story in Backlog with `needs-review` and the intake id as its
`external_id`, unchanged since session 1.

## Latency (seconds, per tool call)

| Tool | Session 1 | Session 2 |
|---|---|---|
| `describe_board` | 11 | 10 |
| `find_items` | 1, 1, 1 | 1, 1, 1 |
| `search_docs` | 6 (two together) | 7 (two together) |
| `get_doc` | — | 1 |
| `propose_item` / `commit_item` | under 1 / 2 | — |

The first `search_docs` of a session includes two Bitwarden lookups (the
email and the token) and the space lookup. The two searches were issued
together, and the server's lock serializes them.

Session 1 made 11 model calls (3,852 output tokens), and session 2 made 7
(2,331).

## Findings

| # | Finding | Disposition |
|---|---|---|
| 1 | Intake called `search_docs` unprompted, in its context step and nowhere else, and read the hit with `get_doc` before answering. When the docs had nothing, it said so rather than inventing a page. | None needed. [tests/test_skills.py](../tests/test_skills.py) holds the retrieval to that step, and `search_docs` to before `get_doc`. |
| 2 | In auto mode, `commit_item` ran without Claude Code's permission prompt, although the README said it always asks. | Fixed in this PR: the README's command passes `--permission-mode manual`, and a test ties it. Session 2 ran that way. |
| 3 | The first publish attempt for the overview, dry run only, used the config whose parent holds the conformance tree. The publisher took the conformance root page as its own root, planned to rename and overwrite it, and reported the other conformance pages as orphans. It matches pages by a scan below the parent, which ignores the label. Nothing was written. | This PR documents one tree per parent page (README, the example config), and the overview went under a fresh page instead. A guard in the publisher, such as checking a page's label before taking it, is a follow-up. |
| 4 | Excerpts end in the page's version messages ("Published from git") and its labels, which the search index includes. | None. `get_doc` gives the clean text, and the skill reads the page before using it. |
| 5 | The optional constraints-and-urgency question came after the search in session 1, and was skipped in session 2. | None. It is optional, and in session 2 the request was settled first. |

Left on `AGKB` by this run: "Team Docs" (made by Chris) and the "Project
Overview" page under it. Left on `AGADM`: AGADM-6 (Backlog,
`needs-review`), which the page now answers, for the PO's review.
