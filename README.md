# agentic_administration

Turn a request typed into a chat window into a well-formed backlog item:
an epic, story, bug or task, with acceptance criteria, filed under the
right parent and in the right sprint, on the tracker your team already
runs. Plane and Jira Cloud are supported; another tracker is one adapter.

> **Status: pre-release.** Everything below runs and has been proven
> against live trackers ([the evidence](#evidence)), but nothing is tagged
> yet. Watch the releases for 0.1.0, the first version to use.

## What it is

- **An MCP server** with eleven tools over one model of work items:
  `describe_board`, `find_items`, `get_item`, `get_iteration`,
  `propose_item`, `commit_item`, `update_item`, `add_comment`,
  `create_iteration`, `close_iteration` and `move_to_iteration`. Any
  MCP-capable agent host can use it. This repo wires up three: Claude
  Code, the Claude Agent SDK and Hermes.
- **Skills** that carry the judgment, as plain `SKILL.md` files: an
  intake conversation for a non-technical request, filing a story, bug or
  epic with Given/When/Then acceptance criteria, sprint rollover,
  planning a calendar's month from templates, and the product owner's
  review pass.
- **One config file per board.** Pointing the agent at your board means
  writing a TOML file: the backend, the connection, and how your
  tracker's types, states and labels map onto the model. No code changes.
  The token stays in the environment or your secret store, never in the
  file.
- **Propose, then confirm.** The agent drafts in chat, the requester says
  yes, and the item lands in the backlog with a review label for the
  product owner. There is **no delete path** anywhere: work is completed
  or cancelled, never removed.
- **Optional docs.** A publisher puts a folder of Markdown on Confluence,
  and a second MCP server lets the agent search it before filing a
  duplicate.

From the requester's side, it goes like this (an illustration, not a
transcript):

> **Requester:** Exporting the monthly report times out when I pick a whole year.<br>
> **Agent:** *asks what should happen instead, finds nothing related on
> the board, and shows a drafted bug: its title, its Given/When/Then
> criteria and where it will go.* File it?<br>
> **Requester:** Yes.<br>
> **Agent:** Filed WEB-142 in the backlog, labelled `needs-review` for the
> product owner.

The chat front end is not the product. It is whatever agent host you
already run, in Discord, Slack, a terminal or an IDE.

## Quick start

You need Python 3.12 or later, [uv](https://docs.astral.sh/uv/), and a
Plane project, on Plane Cloud or self-hosted, with an API key. For Jira,
see [Jira Cloud](#jira-cloud).

```sh
git clone https://github.com/ChrisKornaros/agentic_administration.git
cd agentic_administration
uv sync                # the server and the dev tools, into .venv
uv run pytest          # offline: no tracker or token needed
mkdir -p boards        # your real board configs live here; git ignores it
cp examples/boards/plane.example.toml boards/web-app.toml
```

Edit `boards/web-app.toml` to match your board ([the board
config](#the-board-config)), then check it against the board:

```sh
export PLANE_API_KEY=...   # the variable your config's token_env names
uv run python -m adapters.plane describe boards/web-app.toml
```

`describe` checks the file first and lists every problem in it before it
touches the network. Then it reads the board, which is a read, never a
write. It prints the board's types, states, labels, members, modules and
cycles as JSON, and lists every place the config doesn't fit the board.
Fix those until it ends with `config fits the board.` Until then, the
server refuses every write.

Then load it into a host: [Claude Code](#claude-code), [Hermes](#hermes)
or [your own code](#the-claude-agent-sdk).

## The board config

One TOML file per board, kept in `boards/`. Start from a template in
[examples/boards/](examples/boards/); their comments explain every key.

- [plane.example.toml](examples/boards/plane.example.toml): a Plane project for software work.
- [jira.example.toml](examples/boards/jira.example.toml): a company-managed Jira Scrum project.
- [calendar.example.toml](examples/boards/calendar.example.toml): a calendar
  board on Plane, such as a content calendar, with custom fields and
  templates.

| Key | Required | What it holds |
|---|---|---|
| `backend` | yes | `plane` or `jira` |
| `board_type` | no | `software` (the default) or `calendar` ([calendar boards](#calendar-boards)) |
| `confirm` | no | `always` (the default): the create skills ask before each create. `never`: they commit without pausing. `plan-sprint`, `plan-cycle` and `groom` wait for a yes either way |
| `description` | no | One line on what the board holds, shown when one server serves [several boards](#several-boards) |
| `[connection]` | yes | How to reach the board ([below](#connection)) |
| `[levels]` | yes | How each level of the model exists on the board ([below](#levels)) |
| `[states]` | yes | Each of the five canonical states, `backlog`, `todo`, `in_progress`, `done` and `cancelled`, mapped to a state name in your workflow. New items land in `backlog`; dropped work goes to `cancelled`. On Plane, any state can be mapped, whatever its group |
| `[labels]` | `review`, on a software board | `review`: the label every new item carries until the product owner signs it off. `taxonomy`: the board's other labels, such as `["frontend", "backend"]`, which `describe_board` lists for the agent; the review label needn't be repeated there. Each must already exist on the board |
| `[naming]` | no | `iteration`: the pattern sprint or cycle names follow, built from `YYYY`, `MM` and `DD`; other characters, such as `-`, are kept as written. The default is `"YYYYMM"`, as in `202611`. With `YYYYMM`, `plan-sprint` works out the next month itself; with any other pattern, it asks the PM for the next iteration's name and dates. `item_case`: `title`, `sentence` or `any` (the default). A title in the wrong case gets a warning and a suggested fix |
| `[fields]` | no | Custom fields ([below](#dates-and-custom-fields)) |
| `[templates.<name>]` | no | Item templates ([below](#templates)) |

The file is checked when it loads, and every problem is listed at once.

### Connection

`token_env` is the *name* of the environment variable that holds the API
token, never the token itself; a value that looks like a token fails to
load. Instead of the variable, `<token_env>_BW_ITEM` may name a Bitwarden
item, by id or name, with `BW_SESSION` set (`<token_env>_BW_FIELD` picks
a custom field). Secrets resolve only through
[server/secrets.py](server/secrets.py).

| Backend | Keys |
|---|---|
| `plane` | `token_env`; `workspace`, the workspace slug in your Plane URL; `project`, the project's id, its identifier (such as `WEB`) or its name; `base_url` only for a self-hosted Plane: its API root, `https://<your Plane host>/api/v1` (Plane Cloud's is the default) |
| `jira` | `token_env` and `user_env`, the variables holding a classic API token and the account's email; `site`, such as `https://example.atlassian.net`; `project_key`; `board_id`, the Scrum board whose sprints are the iterations |

### Levels

The model has six levels: Initiative > Epic > Feature > Story / Bug >
Task. Epic, Story, Bug and Task are the core: each is a real item on the
board. Initiative and Feature are optional. A board may collapse each
into a label, a component or a line in the description, so nothing the
requester said is lost. Sprints and cycles are iterations, a separate
axis; so is a grouping such as a component or a module.

Each level in `[levels]` takes exactly one form:

| Form | The level is | Typical use |
|---|---|---|
| `{ type = "Story" }` | a native work-item or issue type, by name or id | Plane work-item types; Jira issue types |
| `{ container = "module" }` | membership in a Plane module | Feature on Plane |
| `{ parent = "epic" }` | an item linked to its parent and marked by this label | a tracker or plan without types (not yet run live) |
| `{ label = "epic" }` | an item marked by this label alone | the same |
| `{ collapse = "label", template = "feature:{name}" }` | no item, but a label (`"label"`), a component (`"component"`) or a description line (`"description_line"`) on the items under it | Initiative and Feature only |

A software board maps all six levels; a calendar board may leave `bug`
out. In a collapse template, `{name}` is the name the request gave, so
`"**Initiative:** {name}"` writes `**Initiative:** Holiday sale` into the
description, and `{level}` is the level's name (`{id}` and `{key}` work
too, for a reference that has them). A label a collapse makes must exist
on the board.

On Plane, work-item types are a feature of the paid plans, and every
live run so far has used them. Without types, map the levels with
`parent` or `label`; neither form has run against a live board yet. A new Plane project has no Bug type, so add one (or
leave `bug` out of a calendar board).

### Calendar boards

`board_type = "calendar"` suits work planned by date a cycle at a time,
such as a content calendar or a hobby project
([the example](examples/boards/calendar.example.toml)). It may leave
`bug` out, and its review is off unless `[labels]` names a `review`
label. Every create still goes through propose and commit.

### Dates and custom fields

An item has a `start_date` and a `target_date`. `[fields]` maps a name
you choose to the tracker's own custom field, by its name or id: a Plane
work-item property, which belongs to one type, or a Jira
`customfield_*`. `describe_board` lists each field with its kind, its
options and the levels that carry it. `propose_item` and `update_item`
take values by your names: true or false, a number, text, an option name,
or a list of option names for a multi-select.

### Templates

A `[templates.<name>]` table saves restating the same item every time.
It sets the level (a story unless it says otherwise), the feature,
labels, custom-field values and the state. Its `title` is a pattern
filled from the item's date (`"{month} {year} Content"`), and its
`description` is a Markdown skeleton, where `{description}` marks the
request's own text. `propose_item(template=…)` fills an item from it; the
request's title, feature and dates win, and its labels and field values
are added. A template's `days` and `dates` are the weekday cadence the
`plan-cycle` skill plans by: a slot on each of those weekdays, and which
of the item's dates the slot's day sets.

## Hosts

### Claude Code

Load the repo as a plugin.
[.claude-plugin/plugin.json](.claude-plugin/plugin.json) registers the
skills and starts the server for the board config, or the directory of
them, in `AGENTIC_ADMIN_BOARD`, a path relative to the repo or an
absolute one. Every board's token goes in the environment. Start from an
empty directory, not the repo, so the repo's developer `CLAUDE.md` stays
out of the requester's context:

```sh
export PLANE_API_KEY=...                       # or the Bitwarden variables above
export AGENTIC_ADMIN_BOARD=boards/<board>.toml      # or boards/, for every board
export AGENTIC_ADMIN_KNOWLEDGE=boards/<docs>.toml   # optional: the team's published docs (below)
T=mcp__plugin_agentic-administration_board__
K=mcp__plugin_agentic-administration_knowledge__
ENABLE_CLAUDEAI_MCP_SERVERS=false claude --plugin-dir /path/to/agentic_administration \
  --tools Skill --permission-mode manual \
  --allowedTools "${T}describe_board ${T}find_items ${T}get_item ${T}get_iteration ${T}propose_item ${K}search_docs ${K}get_doc" \
  --append-system-prompt "You are a team's backlog assistant. Every request is about one of the team's boards, never something to build or design here. New work starts with the intake skill, ending or planning a sprint with plan-sprint, planning a month or cycle of dated work from the board's templates with plan-cycle, and reviewing what's waiting with groom."
```

The requester just types the request; the skills (`/agentic-administration:intake`
and so on) never need typing. The framing line is what makes that work.
Without it, Claude Code reads "I'd like this automated" as a request to
build the automation ([the gate record](transcripts/2026-09-24-phase3-gate.md),
session A). The line names a first skill for each role: a requester's ask
goes to intake, a PM's "roll the sprint over" to plan-sprint, a PM's
"plan November" on a content calendar to plan-cycle, and a product
owner's "groom" to groom.

The other flags keep the session to the backlog. `--tools Skill` leaves
out Claude Code's other built-in tools (shell, files, web), and
`ENABLE_CLAUDEAI_MCP_SERVERS=false` leaves out the requester's claude.ai
connectors. The session gets the Skill tool and the board's eleven
tools, plus the two docs tools when `AGENTIC_ADMIN_KNOWLEDGE` is set. MCP
servers from the requester's own Claude Code configuration still load.
The pre-allowed tools write nothing, so `commit_item` still asks through
Claude Code's permission prompt, a second guard beside the skill's own
yes. `--permission-mode manual` keeps that prompt even when the
requester's default is auto mode, which would let writes through
([the record](transcripts/2026-09-28-phase6b-read-gate.md)). The server
reads the token environment when Claude Code starts, so after unlocking a
vault, restart Claude Code.

### Hermes

To run it from a chat platform through
[Hermes](https://github.com/NousResearch/hermes-agent), give it a profile
of its own: `hermes profile create po --no-skills`. Merge
[examples/hermes/config.fragment.yaml](examples/hermes/config.fragment.yaml)
into the profile's `config.yaml`, and copy
[examples/hermes/SOUL.md](examples/hermes/SOUL.md), the same framing
line, next to it. The fragment:

- starts the server over stdio with `uv run`, pointed at `boards/`, so one
  profile serves every board (name the files instead to serve only some);
- passes each board's token through `env`, read from the profile's
  `.env`, which also holds the profile's own Discord bot token, since
  each profile runs its own gateway;
- registers exactly the eleven tools (Hermes names them
  `mcp__board__<tool>`), plus the two docs tools in its optional
  `knowledge` block, which you leave out without docs;
- loads [skills/](skills/) in place, gives the chat platforms nothing
  else (no shell, files, web or memory), and holds every skill write for
  the operator's approval, so the agent can't swap a skill for its own
  copy.

If Hermes runs in Docker, mount the repo read-only and keep the
fragment's two `UV_*` lines, which put the venv on a writable path.
Hermes has no permission prompt for MCP tools, so the skill's own "wait
for yes" is the only guard before `commit_item`
([the record](transcripts/2026-09-26-phase4-gate.md)).

### The Claude Agent SDK

[examples/agent-sdk/chat.py](examples/agent-sdk/chat.py) is a terminal
chat built on the SDK. It loads the repo as a plugin, as the Claude Code
command does, with the same framing line. The session gets the board's
eleven tools, the docs tools and the Skill tool, nothing else: no shell,
files, web or memory, and no user or project settings. Reads run without
asking; each write asks for a `y` at the terminal. It needs a metered API
key, in `ANTHROPIC_API_KEY` or its Bitwarden item like the board token,
because the SDK's terms don't allow a claude.ai login for products built
on it:

```sh
export PLANE_API_KEY=...                       # or the Bitwarden variables above
export AGENTIC_ADMIN_BOARD=boards/<board>.toml      # or boards/, for every board
export AGENTIC_ADMIN_KNOWLEDGE=boards/<docs>.toml   # optional: the team's published docs
export ANTHROPIC_API_KEY=...                   # or ANTHROPIC_API_KEY_BW_ITEM
uv run --group agent-sdk python examples/agent-sdk/chat.py
```

The `agent-sdk` dependency group installs `claude-agent-sdk`, which
bundles the Claude Code CLI, so nothing else needs installing.

### Any other MCP host

Run the server over stdio and give the host the skills in
[skills/](skills/), plus the framing line from
[examples/hermes/SOUL.md](examples/hermes/SOUL.md):

```sh
uv run python -m server boards/<board>.toml
uv run python -m server boards/            # every board config in the directory
```

No board is read at start. The first tool call reads it, so a missing
token shows up as a tool error the agent can report.

## How it works

### Propose, then commit

Creating an item is two calls. `propose_item` checks the draft against
the board and returns a preview and a token that lasts 30 minutes.
`commit_item(token)` writes exactly that draft, and a retry returns the
same item rather than a duplicate. No tool deletes.

The usual draft is an **intake record** ([schema/intake.py](schema/intake.py)):
one request's problem, outcome, constraints, urgency and related items,
plus the parts it becomes, each with a level, a title, Given/When/Then
acceptance criteria and a placement. `propose_item(intake=…, part=…)`
takes the item from the record and renders its Markdown description, so
the acceptance criteria always land in the item. A split, an epic plus
its stories, places each story under the epic with the parent `#epic`,
which resolves once the epic is committed.

### The skills

Each skill in [skills/](skills/) is a plain `SKILL.md`, with only `name`
and `description` in its frontmatter, so any host that loads skills reads
it.

- **`intake`** asks for the problem and the outcome, looks for related
  items on the board and in the team's docs, decides the shape, and hands
  off to a create skill, or to `plan-cycle` for a dated piece on a
  calendar board. When a published page already answers the request, it
  says so before filing anything.
- **`create-story`** and **`create-bug`** draft the Given/When/Then
  criteria with the requester, propose the item, and commit it after a
  yes.
- **`create-epic`** splits the request into an epic and its stories,
  takes one yes for the whole split, then files the epic first. It asks
  again only if an item's preview differs from what the requester saw.
- **`plan-sprint`** is the PM's rollover. It shows what's left in the
  current iteration and what's ready in the backlog. After one yes, it
  closes the old iteration, finds or creates the next (starting a Jira
  sprint on its first day), and moves the work. Tasks move with their
  story or bug.
- **`plan-cycle`** plans a whole cycle on a board whose templates set a
  cadence, such as a content calendar: the cycle's epic and one item per
  dated slot. The PM edits the list, then sees the exact write-up of
  every item, field and call. After one yes, it finds or creates the
  cycle, files the epic and each item under it, and reads them back. Its
  ids come from the cycle, so a rerun finds what already landed.
- **`groom`** is the product owner's pass over what carries the review
  label. It proposes fixes to each item's title, parent, feature or state
  and flags duplicates. After one yes, it signs each item off: it clears
  the label and moves a story, bug or task from the backlog to `todo`,
  where `plan-sprint` looks for ready work.

### Several boards

One server can serve all of a team's boards: point it at a directory. Each
board is named by its file (`boards/web-app.toml` is `web-app`), and a
TOML file there with no `backend`, such as a docs config, is skipped.
Every tool takes the `board` it acts on, which may be left out when there
is only one. With several, `describe_board()` lists them with their
descriptions, and every other call must name one. The skills use the
board a request names and otherwise ask. A preview names its board, and a
token proposed on one board never commits on another. Adding a board
means adding its file and restarting the server.

## Jira Cloud

Start from [examples/boards/jira.example.toml](examples/boards/jira.example.toml),
for a company-managed Scrum project. Jira's Basic auth pairs a classic
(unscoped) API token with the account's email: `token_env` names the
token's variable and `user_env` the email's. With both in one Bitwarden
item, the email can be the item's username:

```sh
export JIRA_API_TOKEN=... JIRA_USER=you@example.com
# or: export JIRA_API_TOKEN_BW_ITEM="<item>" JIRA_USER_BW_ITEM="<item>" JIRA_USER_BW_FIELD=username BW_SESSION=$(bw unlock --raw)
uv run python -m adapters.jira describe boards/<board>.toml
```

On Jira, Epic, Story, Bug and a sub-task type (the model's Task) are
issue types. Feature can't be a Jira level, so it collapses, as does
Initiative unless the site has a level above Epic. Statuses change
through transitions. A new project's workflow has To Do, In Progress and
Done, so add Backlog and Cancelled (in the Done category) or map two
states onto one status. The board's sprints are the iterations. The
target date is the due date and the start date is the field named "Start
date"; a custom field shows up only once it is on one of the project's
screens. The adapter labels each item `xid:<external_id>`, so a retried
write finds the item it already made. The live runs used a Premium
trial site; nothing in the example config needs Premium, but Free and
Standard haven't been run.

## Publishing docs to Confluence (optional)

To publish a folder of Markdown to Confluence (one way: git stays the
source), copy
[examples/knowledge/confluence.example.toml](examples/knowledge/confluence.example.toml)
to `boards/<name>.toml`. It uses the same site, token and email as a Jira
board config. Then:

```sh
uv run python -m knowledge publish docs/ --config boards/<name>.toml           # dry run: reads, plans, writes nothing
uv run python -m knowledge publish docs/ --config boards/<name>.toml --apply   # writes
```

Each folder becomes a page, with its `index.md` (or `README.md`) as the
body, and each other `.md` file becomes a page under it. The tree goes
under the page named by `space.parent`. A tree is known by its
`publish.label`: the publisher counts a page as part of the tree only if
it carries that label, so trees can share a parent page but each needs a
label of its own. A page's title is its first `#` heading, or else its
file name, and relative links between files become links between pages.
A re-run writes only what changed. A page whose file is gone is reported
for a person to archive, and nothing is ever deleted. Each run writes at
most `publish.max_writes` pages, and the next run picks up the rest.
Images aren't published yet.

To publish on every push instead, copy
[examples/knowledge/publish-docs.yml](examples/knowledge/publish-docs.yml)
into the docs repo's `.github/workflows/`. Its header lists the config
file and the two repository secrets it needs.

Agents read the published docs through a second MCP server, `knowledge`,
with two read-only tools. `search_docs(query, k)` returns up to `k`
pages, best first, each with its id, title, URL and an excerpt.
`get_doc(ref)` reads one page, by that id or URL, as Markdown. They see
only the pages the same config publishes: its space, carrying its label.
Search is Confluence's own ranked search, so a page published a moment
ago may take a few seconds to show up. The plugin starts this server with
the config in `AGENTIC_ADMIN_KNOWLEDGE`; with none, it serves no tools,
so a team without docs sets nothing:

```sh
uv run python -m knowledge serve --config boards/<name>.toml   # stdio
```

## Proving an adapter

The conformance suite proves an adapter against a **throwaway** project
with real writes, never a delete:

```sh
uv run python -m conformance boards/<board>.toml --dry-run   # list the cases
uv run python -m conformance boards/<board>.toml
uv run python -m conformance.knowledge boards/<name>.toml    # the publisher, under a fresh, empty parent page
```

[conformance/README.md](conformance/README.md) has the cases and the
dated results. A new tracker is a new adapter written against
[adapters/base.py](adapters/base.py) and proven by this suite.

## Evidence

Each claim above has a dated record in the repo:

- **Adapters:** Plane and Jira Cloud pass the conformance suite live, and
  the Confluence publisher passes its own
  ([results](conformance/README.md#results)).
- **Intake from a plain conversation:** a correctly placed story, with
  acceptance criteria and the review label, filed from Claude Code
  ([record](transcripts/2026-09-24-phase3-gate.md)) and again from
  Discord through Hermes ([record](transcripts/2026-09-26-phase4-gate.md)).
- **Sprint rollover** on both trackers through the Agent SDK example, with
  one yes from the PM ([record](transcripts/2026-10-02-phase6-gate.md)).
- **Docs before duplicates:** intake found a published page that
  answered a request and answered from it, in Claude Code
  ([record](transcripts/2026-09-28-phase6b-read-gate.md)) and through
  Hermes ([record](transcripts/2026-10-03-hermes-docs-run.md)).
- **A real board:** the first run on a real, non-software board, including
  groom's sign-off ([record](transcripts/2026-10-05-food-content-week.md)).
- **Several boards and a calendar:** one agent over two boards asked which
  board when a request named none, then planned a month of a real content
  calendar, 27 items, after one yes, and the read-back matched
  ([record](transcripts/2026-10-13-phase6c-gate.md)).
- **The APIs themselves:** dated read-only probes of each tracker
  ([probes/](probes/README.md)).

Not yet run live: the `parent` and `label` level forms; `groom` under a
host (its sign-off ran from a developer session); Jira below Premium; the
`publish-docs.yml` workflow.

## Development

```sh
uv sync            # dev deps (pytest) into .venv
uv run pytest      # offline, never a live tracker; live checks are probes/ and conformance/
```

The one runtime dependency is the official
[`mcp`](https://pypi.org/project/mcp/) SDK (v2), for the servers; the
model, config, intake schema and adapters are standard library only.
Comments and docs cite design decisions as `roadmap/14 D<n>`: that design
doc lives in the author's private research repo, and each decision's
effect is in the code, its tests and this README. [CLAUDE.md](CLAUDE.md)
is the contract for coding agents working on the repo.

```
agentic_administration/
├── .claude-plugin/    # plugin.json: the skills and both MCP servers as a Claude Code plugin
├── server/            # the board MCP server, the canonical model, the board config, secrets
├── adapters/          # base.py (the interface and errors), plane/, jira/
├── skills/            # intake, create-story, create-bug, create-epic, plan-sprint, plan-cycle, groom
├── schema/            # the intake record and its Markdown rendering
├── knowledge/         # the Markdown → Confluence publisher and the docs MCP server
├── conformance/       # the live adapter and publisher suites, with dated results
├── examples/          # board configs, the Hermes wiring, the Agent SDK chat, the publisher config and CI job
├── probes/            # dated read-only API checks
├── transcripts/       # dated summaries of live sessions
├── tests/             # offline tests
└── boards/            # your real configs (gitignored)
```

## License

MIT — see [LICENSE](LICENSE).
