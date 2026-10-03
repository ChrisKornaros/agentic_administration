# Hermes docs run: intake answers from the docs, from Discord (2026-10-03)

Two items left open after the Phase 6 gate: the `po` Hermes profile on
ms01 had no `knowledge` block, and the framing line every host carries
since Phase 6 step 4 (D34) hadn't run a Discord request. One request
covered both. **PASS:** po routed it to `intake`, searched the docs,
read the hit with `get_doc`, answered from the page with its link, and
filed nothing.

This isn't a phase gate. It repeats the 6b read gate's second session
([the record](2026-09-28-phase6b-read-gate.md)) through Hermes instead
of Claude Code. This is a summary: the request and the page text stay out
of git.

## Setup

- **Host:** Hermes Agent v0.19.1 (2026.7.30) in Docker on ms01, the `po`
  profile and its own Discord bot, in #plane.
- **Model:** Opus 5.5 (`claude-opus-5-5`), as in the earlier gates.
- **Wiring:** [examples/hermes/config.fragment.yaml](../examples/hermes/config.fragment.yaml)
  with ms01's paths. The `knowledge` block went in today, with `knowledge`
  in the `cli` and `discord` toolsets; the profile's `.env` gained the
  Jira token and email (Bitwarden). The repo is mounted read-only at
  `main`, so the server and skills were the merged ones, and `SOUL.md`
  matches the example's.
- **Servers:** `board` on Plane, throwaway project `AGADMIN`; `knowledge`
  on Confluence, throwaway space `AGKB`, scoped to the "Team Docs" tree
  (label `md-published`), whose one page is the 6b gate's "Project
  Overview".
- **Before the request:** inside the container, a stdio `tools/list`
  against `knowledge serve` listed `search_docs` and `get_doc` with no
  secrets set (the server reads them per call). After the restart the
  gateway registered both as `mcp__knowledge__*`.
- **Requester:** Chris, asking for a short write-up of what the project
  is and what it tests, for new people. The request didn't mention docs,
  Confluence or tools.

## The session

| Step | What happened |
|---|---|
| Start | `skill_view("intake")`. The framing line sent a request an agent could have answered by writing the overview itself to `intake` |
| Questions | none. The request gave the problem and the outcome, and `intake` asks only for what's missing. The optional constraints-and-urgency question was skipped, as in the 6b gate's second session, because the docs settled the request first |
| Context step | `describe_board`, one key-word `find_items` and `search_docs`, issued together. The search found the page |
| Read | `get_doc` on the hit, with a second key-word `find_items`, before telling the requester anything from the page |
| Told the requester | the page's title, link and what it says. It added that the page names the Jira board while this thread's board is Plane, and asked whether the page covered it. It offered to file a request to fix or expand the page, only if wanted |
| Filed | nothing |

No write tool was called: the session was read from po's `state.db`
(opened `mode=ro`). There was no new item to read back on the board.

## Latency and cost

The reply came 33 s after the request, from 4 model calls (1,310 output
tokens). The three reads issued together returned 11–14 s after they
were sent. `get_doc` and the second `find_items` took about 1 s.

## Findings

| # | Finding | Disposition |
|---|---|---|
| 1 | The `knowledge` server behaved under Hermes as under Claude Code: the first search found the page, and the page was read before use. | None needed. The example's block is unchanged. |
| 2 | The framing line routed a request to write an overview to `intake`, not to writing one. | None needed. |
| 3 | The model's short note sent with the `get_doc` call ("A doc hit looks like it answers this; read it before saying anything.") was posted to the channel, so the requester saw a paraphrase of the skill. | Open. It's Hermes posting text sent alongside tool calls; flagged for the AOR catch-up. No skill change. |
| 4 | No `find_items(level="epic")`, which `intake` says to run every time. | None. Epics matter only for placing a new item, and nothing was filed. The 6b gate's second session ran it. |
| 5 | The answer ran to three bullets where the skill says "a sentence or two", and added the board mismatch, which comes from `describe_board`, not the page. | None. The mismatch note is true and useful, and the request asked for a write-up. |
| 6 | The page names only the Jira board, not Plane. | None. `AGKB` is a throwaway space and goes with the trial on 2026-10-27. |
| 7 | Hermes put a "no home channel is set" notice in the requester's channel before its reply. Saving a home channel afterwards rewrote the profile's `config.yaml` as plain YAML: the keys are unchanged, and the comments are gone. | Flagged for the AOR catch-up. The wiring's reasons live in the example here and AOR's copy, not in ms01's file. |

Left on the boards by this run: nothing.
