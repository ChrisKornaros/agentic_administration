# agentic_administration

An agent-operated administration layer for engineering teams: turn a
request typed into a chat window into a well-formed backlog item —
epic, feature, story, bug, or task — filed under the right parent, in
the right sprint, on whatever tracker your team already runs.

> **Status: building (2026-09).** Nothing is released yet. Both backends,
> Plane and Jira Cloud, pass the conformance suite against live throwaway
> projects ([the results](conformance/README.md#results)). The MCP server, the intake schema and the first four skills
> have filed a correctly placed story with acceptance criteria and the
> review label from a plain-language Claude Code conversation
> ([the gate record](transcripts/2026-09-24-phase3-gate.md)), and did it
> again from Discord through Hermes with no step dropped
> ([the Hermes record](transcripts/2026-09-26-phase4-gate.md)). The sprint
> rollover and grooming skills are written and haven't run live yet.
> Publishing a repo's Markdown docs to Confluence, for people to read and
> agents to search, has started: a read-only probe has checked the API
> ([probes/](probes/README.md)), and the publisher is written and tested
> offline but hasn't run live yet. Watch the releases for the first usable
> version.

## What it is

- **A small MCP server** exposing eleven *domain* tools —
  describe board, find / get item, get iteration, propose + commit
  item, update item, comment, create / close iteration, move to
  iteration — over a canonical work-item model. Your agent runtime
  (Claude Code, the Claude Agent SDK, Hermes, or any MCP-capable host)
  plugs it in.
- **Skills** that carry the judgment: an intake conversation that
  fills a requirements schema from a non-technical request, the
  decomposition of one request into epic + stories with acceptance
  criteria, sprint planning and rollover, and a backlog-grooming pass.
- **Backend adapters** that map the canonical model onto a real
  tracker's API: Plane and Jira Cloud (Premium/Enterprise). A
  parent-only generic mode covers trackers without typed hierarchies.
- **Propose-then-confirm by default.** The agent drafts in chat, the
  requester confirms, the item lands in the backlog flagged for a
  product owner's review. The tool has **no delete path**; work is
  completed or cancelled, never removed.

Built on context-engineering practice: conventions, the intake schema,
and the board model load into the agent lazily as skills, and the
tool surface enforces the rules the prompts describe.

## What "tracker-agnostic" means here

For a **supported backend**, pointing the tool at your board is a
settings change: one config file naming the backend, the connection,
how the canonical levels map onto your tracker's types, and how the
canonical states map onto your workflow. No secrets in the file — the
token comes from the environment or your secret store.

For a **new backend**, it is an adapter written against a documented
interface, proven by a conformance suite that runs against a throwaway
project on that tracker. The suite ships with the repo so the claim is
testable, not aspirational.

## The canonical model

Initiative > Epic > Feature > Story / Bug > Task. Epic > Story / Bug >
Task is the guaranteed core; Initiative and Feature are optional levels
that each backend either materializes natively or collapses into a
label, component, or description line, so nothing the requester said
is lost. Sprints are iterations; the cross-cutting grouping (component,
module, area) is a separate axis, not a level.

## Chat interfaces

The chat bot is not the product. The server, the skills, and the intake
schema are. A Discord, Slack, or Telegram front end is whatever agent
runtime you already operate. The repo has a Hermes configuration
([examples/hermes/](examples/hermes/)) as a reference wiring, and a
runnable Claude Agent SDK example ([examples/agent-sdk/](examples/agent-sdk/)).

## Layout (planned; ✅ = exists)

```
agentic_administration/
├── README.md
├── LICENSE            # MIT
├── CLAUDE.md          # agent context; modules/ + .claude/skills/ vendored from agentic_optimization_research  ✅
├── .claude-plugin/    # plugin.json: loads skills/ + the MCP server into Claude Code  ✅
├── server/            # the MCP server + canonical model  ✅ model.py, config.py, secrets.py, service.py, mcp_app.py
├── adapters/          # plane/, jira/, generic/  ✅ base.py (interface + errors), plane/, jira/
├── boards/            # real board configs — gitignored; examples/boards/ has the template
├── skills/            # ✅ intake, create-story, create-bug, create-epic, plan-sprint, groom
├── schema/            # the intake schema + its Markdown rendering  ✅ intake.py (the board config schema is server/config.py)
├── knowledge/         # Markdown docs → Confluence, and the docs' MCP server  ✅ the publisher (offline-tested)
├── conformance/       # the adapter test suite  ✅ Plane and Jira pass live
├── examples/          # board configs, an Agent SDK bot, a Hermes config, a publisher config  ✅ boards/, hermes/, agent-sdk/, knowledge/
├── probes/            # dated read-only API checks (evidence)  ✅
├── transcripts/       # dated summaries of live requester sessions (evidence)  ✅
└── tests/             # offline unit tests — never a live tracker  ✅
```

## Development

Python ≥ 3.12, managed with [uv](https://docs.astral.sh/uv/). The one
runtime dependency is the official [`mcp`](https://pypi.org/project/mcp/)
SDK (v2), for the server; the model, config, intake schema and adapters
are standard library only.

```sh
uv sync            # dev deps (pytest) into .venv
uv run pytest      # offline; live checks are probes/ and conformance/
```

To point the Plane adapter at a board: copy
[examples/boards/plane.example.toml](examples/boards/plane.example.toml)
to `boards/<board>.toml` (gitignored), then read the board and check the
config against it — a read, never a write:

```sh
export PLANE_API_KEY=...                       # or, via Bitwarden:
export PLANE_API_KEY_BW_ITEM="Plane API" BW_SESSION=$(bw unlock --raw)
uv run python -m adapters.plane describe boards/<board>.toml
```

It prints the board's types, states, labels, members, modules and cycles
and lists every config-vs-board mismatch; the adapter refuses every write
until that list is empty. Secrets resolve through `server/secrets.py`
only: the env var named by `token_env`, or the Bitwarden item named by
`<token_env>_BW_ITEM` (custom field via `<token_env>_BW_FIELD`). The item
is an id or a name; a name that several items match resolves to the one
named exactly that.

**Jira Cloud** works the same way from
[examples/boards/jira.example.toml](examples/boards/jira.example.toml), for a
company-managed Scrum project. Its Basic auth pairs a classic (unscoped) API
token with the account email: `token_env` names the token's variable,
`user_env` the email's. With both in one Bitwarden item, the email can be
the item's username:

```sh
export JIRA_API_TOKEN_BW_ITEM="<item>" JIRA_USER_BW_ITEM="<item>" JIRA_USER_BW_FIELD=username
export BW_SESSION=$(bw unlock --raw)
uv run python -m adapters.jira describe boards/<board>.toml
```

On Jira, Epic, Story, Bug and a sub-task type (the canonical Task) are
issue types. Initiative and Feature collapse (Premium's custom levels sit
only above Epic), statuses change through transitions, the board's sprints
are the iterations, and the idempotency key is an `xid:<external_id>` label.

To run the MCP server for a board (stdio; the board is first read on the
first tool call, so a token problem shows up as a tool error):

```sh
uv run python -m server boards/<board>.toml
```

Creating an item is two calls: `propose_item` checks the draft against the
board and returns a preview and a 30-minute token; `commit_item(token)`
writes exactly that draft, and a retry returns the item rather than a
duplicate. No tool deletes.

The usual draft is an **intake record** ([schema/intake.py](schema/intake.py)):
one request's problem, outcome, constraints, urgency and related items,
plus the parts it becomes, each with a level, a title, Given/When/Then
acceptance criteria and a placement. `propose_item(intake=…, part=…)`
takes the item from the record and renders its Markdown description, so
the acceptance criteria always land in the item body. A split (an epic
plus its stories) places a story under the epic with the parent `#epic`,
which resolves once the epic is committed.

The skills in [skills/](skills/) run that conversation. Each is a plain
`SKILL.md` (only `name` and `description` in the frontmatter, so any
skill-loading host reads it):

- **`intake`** asks for the problem and the outcome, looks for related
  items, decides the shape, and makes the intake id (`YYYYMMDD-<slug>`).
- **`create-story`** and **`create-bug`** draft the Given/When/Then
  criteria with the requester, propose the item, and commit it after a yes.
- **`create-epic`** splits the request into an epic and its stories, takes
  one yes for the whole split, then files the epic first. It asks again
  only if an item's preview differs from what the requester saw.

- **`plan-sprint`** is the PM's rollover. It shows the leftovers of the
  current iteration and the backlog picks, and after one yes it closes the
  old iteration, finds or creates the next one (which starts a Jira sprint
  on its first day), and moves the work. Tasks move with their story or
  bug.
- **`groom`** is the PO's review pass over what carries the review label
  (`find_items(label=…)`). It proposes fixes to each item's title, parent,
  feature or state and flags duplicates. After one yes it signs each item
  off: it clears the label and moves a story, bug or task from Backlog to
  `todo`, where `plan-sprint` looks for ready work. An item the PO holds
  stays in the queue.

With the board's `confirm = "never"`, the create skills commit without
pausing; `plan-sprint` and `groom` still wait for their yes.
Looking up related items happens in one step of `intake` (the board's own
search by default), so another retrieval source replaces only that step.

To try it in **Claude Code**, load the repo as a plugin.
[.claude-plugin/plugin.json](.claude-plugin/plugin.json) registers the
skills and starts the server for the board in `AGENTIC_ADMIN_BOARD`, which
is a path relative to the repo or an absolute one. Start from an empty
directory, not the repo, so the repo's developer `CLAUDE.md` stays out of
the requester's context:

```sh
export PLANE_API_KEY=...                       # or the Bitwarden variables above
export AGENTIC_ADMIN_BOARD=boards/<board>.toml
T=mcp__plugin_agentic-administration_board__
ENABLE_CLAUDEAI_MCP_SERVERS=false claude --plugin-dir /path/to/agentic_administration \
  --tools Skill \
  --allowedTools "${T}describe_board ${T}find_items ${T}get_item ${T}get_iteration ${T}propose_item" \
  --append-system-prompt "You are a team's backlog assistant. Every request is about the team's board, never something to build or design here. New work starts with the intake skill, ending or planning a sprint with plan-sprint, and reviewing what's waiting with groom."
```

The skills show up as `/agentic-administration:intake` and so on, but a
requester needs none of them: they just type the request. The framing line
is what makes that work. Without it, Claude Code reads "I'd like this
automated" as a request to build the automation
([the gate record](transcripts/2026-09-24-phase3-gate.md), session A).
The line names a first skill for each role: a requester's ask goes to
intake, a PM's "roll the sprint over" to plan-sprint, and a PO's "groom"
to groom.
`--tools Skill` leaves out Claude Code's other built-in tools (shell,
files, web), and `ENABLE_CLAUDEAI_MCP_SERVERS=false` leaves out the
requester's claude.ai connectors, so the session gets the Skill tool and
the board's eleven, as the Agent SDK example below does. MCP servers from
the requester's own Claude Code configuration still load.
The tools pre-allowed above write nothing, so `commit_item` still asks
through Claude Code's permission prompt, a second guard beside the skill's
own yes. The server reads the token environment when Claude Code starts,
so after unlocking a vault, restart Claude Code.

To run it from chat through **Hermes**, give it a profile of its own:
`hermes profile create po --no-skills`, then merge
[examples/hermes/config.fragment.yaml](examples/hermes/config.fragment.yaml)
into the profile's `config.yaml` and copy
[examples/hermes/SOUL.md](examples/hermes/SOUL.md), which is the same framing
line, next to it. The fragment starts the server over stdio with `uv run`,
passes the token through `env`, registers exactly the eleven tools (Hermes
names them `mcp__board__<tool>`), loads [skills/](skills/) in place, and gives
the chat platforms nothing else: no shell, files, web or memory. It also
holds every skill write for the operator's approval, so the agent can't
replace a skill with its own local copy. The profile's `.env` holds the
board token and its own Discord bot token, since each profile runs its own
gateway. If Hermes runs in Docker, mount the repo read-only and keep the
fragment's two `UV_*` lines, which put the venv on a writable path. Hermes
has no permission prompt for MCP tools, so the skill's own "wait for yes" is
the only guard before `commit_item`
([the Hermes gate record](transcripts/2026-09-26-phase4-gate.md)).

To run it from your own code, the **Claude Agent SDK** example
[examples/agent-sdk/chat.py](examples/agent-sdk/chat.py) is a terminal chat
that loads the repo as a plugin, as the Claude Code command above does,
with the same framing line. The session gets the board's eleven tools and
the Skill tool, nothing else: no shell, files, web or memory, and no user
or project settings. Reads run without asking; each write asks for a `y`
at the terminal. It needs a metered API key, in `ANTHROPIC_API_KEY` or its
Bitwarden item like the board token, because the SDK's terms don't allow
a claude.ai login for products built on it:

```sh
export PLANE_API_KEY=...                       # or the Bitwarden variables above
export AGENTIC_ADMIN_BOARD=boards/<board>.toml
export ANTHROPIC_API_KEY=...                   # or ANTHROPIC_API_KEY_BW_ITEM
uv run --group agent-sdk python examples/agent-sdk/chat.py
```

The `agent-sdk` dependency group installs `claude-agent-sdk`, which bundles
the Claude Code CLI, so nothing else needs installing.

To prove an adapter against a **throwaway** project (real writes, never
a delete), run the conformance suite:
`uv run python -m conformance boards/<board>.toml` (add `--dry-run` to
list the cases first). See [conformance/README.md](conformance/README.md)
for the cases and the dated results.

To publish a folder of Markdown docs to **Confluence** (one way: git stays
the source), copy
[examples/knowledge/confluence.example.toml](examples/knowledge/confluence.example.toml)
to `boards/<name>.toml`. It uses the same site, token and email as the Jira
board config. Then:

```sh
uv run python -m knowledge publish docs/ --config boards/<name>.toml           # dry run: reads, plans, writes nothing
uv run python -m knowledge publish docs/ --config boards/<name>.toml --apply   # writes
```

Each folder becomes a page, with its `index.md` (or `README.md`) as the
body, and each other `.md` file becomes a page under it. The whole tree goes
under the page named by `space.parent`. A page's title is its first `#`
heading, or else its file name. Relative links between the files become
links between the pages. A re-run writes only what changed, and an edit
makes one new page version. A page whose file is gone is reported for a
person to archive, and nothing is ever deleted. Each run writes at most
`publish.max_writes` pages, and the next run picks up the rest. Images
aren't published yet.

## License

MIT — see [LICENSE](LICENSE).
