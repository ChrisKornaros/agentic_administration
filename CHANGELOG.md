# Changelog

Every release, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until
1.0, a minor release may change the board config or the tools, and its
entry says how.

## [Unreleased]

### Added

- **A ClickUp adapter, its read side.** A third `backend`, `clickup`
  ([examples/boards/clickup.example.toml](examples/boards/clickup.example.toml)):
  the board is one Space of a workspace, named by `workspace` and `space`,
  with an optional `sprint_folder`. `python -m adapters.clickup describe`
  reads the Space and checks the config against it, and `find_items`,
  `get_item` and `get_iteration` read it. A level is a task type or a
  marker tag, states are the Space's statuses, labels its tags, and the
  sprints the Lists of the named Folder, each with a state taken from its
  start and end. A personal token sees every Space its owner does, so a
  task outside the configured Space is not found.
- **The ClickUp adapter's write side.** It passed the live conformance
  suite on a throwaway Space on 2026-11-24, 9 cases with `fields`
  skipped. Two new connection keys: `list`, the List a new item is
  filed in (an item with a parent goes into its parent's List), and
  `xid_field`, the text custom field that holds the idempotency key, which
  `find_items(external_id=…)` matches exactly. `create_item`,
  `update_item` and `add_comment` write; every write to a task first
  checks that the task is in the configured Space. A task enters a sprint
  by being added to its List. ClickUp's API cannot make or close a
  sprint, so `create_iteration` finds one by name and `close_iteration`
  confirms one that has ended, and each says so otherwise. Members are
  read from the workspace. Custom fields, links and a container level are
  not wired. `python -m conformance` runs on a ClickUp config, with one
  `sprints` case in place of the three sprint cases.
- **One DELETE, and no other.** ClickUp takes a tag off a task with
  `DELETE /task/{id}/tag/{name}` and has no other way to clear a label.
  The adapter sends it; the task and the Space's tag both stay. Its
  transport refuses every other DELETE, and the no-delete tests now count
  exactly that call.
- **Open issues from a code host, for planning.** A third, optional MCP
  server, `issues` (`python -m issues serve --config <toml>`), has one
  read tool. `find_open_issues(limit)` lists a repository's open issues,
  most recently updated first, each with its number, title, URL, labels,
  last-updated day and `item_keys`: the board keys its text names, found
  by the config's `key_pattern`. Pull requests are left out and nothing
  is written. GitHub is the first source, over its REST API with the
  standard library; the config
  ([examples/issues/github.example.toml](examples/issues/github.example.toml))
  names the repository and the variable holding a token that can read its
  issues. The plugin starts the server from `AGENTIC_ADMIN_ISSUES` and
  serves no tools without it; the Hermes example has the block.
- **A Microsoft Teams bot** ([examples/teams/](examples/teams/)), in two
  parts. `bridge.py` has no Teams in it: one agent session per chat
  conversation, resumed across restarts, with turns in order, `/new` to
  start over, and a yes from the sender before each write. It reads from
  the environment whose usage pays: with a metered credential it serves
  the owner and an allow-list, and on a Claude plan login it serves the
  owner alone. `agent.py` runs a turn on the Agent SDK and `terminal.py`
  drives the bridge with no chat platform. `bot.py` is the bot, on
  Microsoft's Teams SDK for Python (the optional `teams` dependency
  group): direct chats only, an answer to Teams at once with the turn
  run behind it, "Working on it…" replaced by the agent's first words,
  and `--playground`, `--socket` or HTTPS to run it. It has run end to
  end on a laptop in Microsoft's Agents Playground (2026-11-24), not in a
  tenant. Before each write the bridge says what is about to change in
  words, with the item, the board and each value, and notes where labels
  or assignees replace the current ones. `AGENTIC_ADMIN_INSTRUCTIONS`
  adds a team's own rules for the assistant after the framing line.
  With `--playground` the bot sends `markdown`, since the Playground
  refuses the `extendedmarkdown` that Teams takes.
- **A draft outlasts a server restart.** `propose_item` also writes the
  draft to a small JSON file, in the directory `AGENTIC_ADMIN_DRAFTS`
  names or `~/.cache/agentic-administration/drafts`, and `commit_item`
  finds it there. A host that starts the server anew for every message,
  as the Teams bot does, could not commit after the person's yes before.
  A file is read only for a token-shaped name and only by the board and
  tracker project it was drafted for, it expires with its token, and the
  next proposal removes the expired ones. Set the variable empty to keep
  drafts in memory alone.
- **A new ClickUp task comes back with its key.** ClickUp adds a task's
  custom id a moment after the create answers, so `create_item` reads the
  task again, up to twice, when it came back without one. It does not
  wait once a task has shown that the Space issues no custom ids.
- **ClickUp: a tag with a slash is refused before anything is written.**
  ClickUp's API takes no form of a slash in a tag's address, so adding
  `ui/ux` to a task answered 404 after the rest of the update had gone.
  `update_item` now refuses the whole update first and says to change the
  tag in ClickUp. A slash tag already on a task is kept.
- **`find_items` returns a long list whole on Claude Code.** Claude Code
  saves a tool result over about 50,000 characters to a file, which a
  host with no file tool, such as the Teams bot, cannot open; a sprint of
  85 items came back in pieces. The tool now declares a larger limit
  (`anthropic/maxResultSizeChars`), which other hosts ignore.
- **Azure DevOps as a code host: its open pull requests.** The `issues`
  server takes a second `kind`, `azure_devops`
  ([examples/issues/azure-devops.example.toml](examples/issues/azure-devops.example.toml)).
  Azure Repos has no issues of its own, so `find_open_issues` lists a
  repository's active pull requests there, or a whole project's with
  `repository = "Project/*"`, newest first. Each carries the day it was
  opened, and `item_keys` come from its title, its source branch and its
  description, in that order. The token is a personal access token
  (Basic auth) or, with `auth = "bearer"`, a Microsoft Entra token. No
  redirect is followed, so the token goes nowhere but the configured
  host, and a sign-in page in place of JSON is reported as a refused
  token. Only GET is sent.
- **`plan-sprint` shows open issues with no board item.** Where the host
  has `find_open_issues`, the skill sorts each open issue into on the
  board (a key it names), linked (an item whose links hold its URL) or
  no board item found, and lists the last group in the plan. It changes
  none of them, and its text names no code host.
- **Links on a work item, on Plane.** `update_item` takes `links`, a
  list of URLs (an issue or a pull request, say). It adds each one the
  item does not carry yet and never removes one, so sending the same
  list twice writes nothing. `get_item` returns the item's links, oldest
  first; `find_items` does not read them. A link must be an http(s) URL.
  On Jira `links` is refused with a clear message, since its remote
  links are not wired yet. Not in `propose_item`: a new item gets its
  links by an `update_item` after the commit.
- **Production notes below a caption.** A board's `[caption]` table
  takes an optional `notes_separator`, a line of three or more dashes
  (`"------"`). Below it, an item's description holds production notes,
  which the tool that imports the caption reads apart and never
  publishes. `describe_board` reports it, `null` when it is left out, and
  a value that is not dashes alone is a config problem. The
  `draft-caption` skill checks the caption above the line alone, keeps
  the notes as read when only the caption changes (and the caption when
  only the notes change), drafts notes only when asked, and writes both
  parts in its one `update_item`. `plan-cycle` lets a slot's notes ride
  its description, except where the template's skeleton adds text after
  `{description}`, which would land among the notes: that slot gets the
  caption alone and the notes go on the filed item. The server still
  enforces none of it.

### Fixed

- **Plane: a horizontal rule reads back as a line.** A description read
  through the adapter lost a rule, so the text on each side of it ran
  together, and an `update_item` built from that read would write it back
  merged. A read now returns a `<hr>`, and the node Plane's editor stores
  for a rule typed in its UI, as a `---` line between blank lines. Writes
  are unchanged: a line of dashes is still written as text. The editor's
  stored form is taken from Plane's open-source editor, not yet read back
  from a live board.

- **Plane: a description read back keeps the blank line between
  paragraphs.** `get_item` and `find_items` returned a single line break
  where the board stores two paragraphs, so text written as paragraphs
  never read back as written. A read now returns a blank line after a
  paragraph, a heading, a quote and a code block, as the Jira adapter
  does. A list item and a `<br>` still end with one newline.

## [0.1.0] - 2026-10-27

The first release: a backlog agent for Plane and Jira Cloud, proven
against live trackers ([the evidence](README.md#evidence)).

### Added

- **The board MCP server**, `python -m server`, with eleven tools over
  one model of work items: `describe_board`, `find_items`, `get_item`,
  `get_iteration`, `propose_item`, `commit_item`, `update_item`,
  `add_comment`, `create_iteration`, `close_iteration` and
  `move_to_iteration`. Creating an item is propose, then commit, with a
  30-minute token, and a retried commit returns the same item. No tool
  deletes. One server can serve several boards.
- **Two adapters:** Plane, on Plane Cloud or self-hosted, and Jira Cloud,
  for a company-managed Scrum project. Both pass the live conformance
  suite.
- **The board config**, one TOML file per board. It maps the model's
  levels, states and labels onto the board, and sets the naming rules,
  the board type (`software` or `calendar`), custom fields and item
  templates. Each state needs a status of its own: a config that maps two
  onto one fails to load, since a read maps a status back to one state.
  Tokens stay in the environment or Bitwarden.
- **The intake record**: one request and the parts it becomes, rendered
  to Markdown with Given/When/Then acceptance criteria.
- **Seven skills:** `intake`, `create-story`, `create-bug`, `create-epic`,
  `plan-sprint`, `plan-cycle` and `groom`. Where the host has the docs,
  `groom` reads the team's review rules from them, one link deep, and a
  page never adds a write the skill doesn't make.
- **Docs on Confluence (optional):** a one-way Markdown publisher,
  `python -m knowledge publish`, with a GitHub Actions example, and a
  second MCP server, `knowledge`, with `search_docs` and `get_doc`. The
  publisher carries an Obsidian vault's graph: a `[[wikilink]]` lands on
  the note it names, front matter becomes a table, and each page ends with
  the pages that link to it, so an agent with only `get_doc` can walk the
  graph both ways.
- **[SETUP.md](SETUP.md), the setup in order,** for a coding agent given
  the repo's URL ("set this up for my organization") or for a person:
  what to ask, the config, fitting it with `describe`, the token, the
  host, the first item and the team's hand-off, with rules that keep the
  agent away from tokens and board writes.
- **Three hosts:** a Claude Code plugin, a Hermes profile, and a terminal
  chat on the Claude Agent SDK.
- **The proof:** live conformance suites for both adapters and the
  publisher, dated read-only API probes, summaries of the live gate
  sessions, a guide to writing an adapter, and an offline test suite
  that CI runs on every push and pull request.

### Not yet run live

- The `parent` and `label` level forms, which a Plane plan without
  work-item types needs.
- Jira below Premium, and a team's own Jira board: every Jira run used a
  throwaway project.
- The setup by someone other than the author.

### Known issues

- On Plane, `find_items` returns every item's `fields` empty. `get_item`
  reads the values.
- On Plane, `get_item` by key, such as `WEB-12`, reports no iteration.
  By id, and in `find_items`, the iteration is there.
- Each board paces its own calls, so two boards on one token can reach
  the tracker's rate limit twice as fast.
- "Today" is the machine's local date, while iteration dates are read in
  the board's time zone, so near midnight the two can differ by a day.
- `describe` checks status names only, not the transitions into them,
  the board's columns or Cancelled's category.
- A front-matter value written as a YAML block scalar (`key: |`) shows
  as a lone `|` in the page's table.

[0.1.0]: https://github.com/ChrisKornaros/agentic_administration/releases/tag/v0.1.0
