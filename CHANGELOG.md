# Changelog

Every release, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until
1.0, a minor release may change the board config or the tools, and its
entry says how.

## [0.1.0] - 2026-10-19

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
  templates. Tokens stay in the environment or Bitwarden.
- **The intake record**: one request and the parts it becomes, rendered
  to Markdown with Given/When/Then acceptance criteria.
- **Seven skills:** `intake`, `create-story`, `create-bug`, `create-epic`,
  `plan-sprint`, `plan-cycle` and `groom`.
- **Docs on Confluence (optional):** a one-way Markdown publisher,
  `python -m knowledge publish`, with a GitHub Actions example, and a
  second MCP server, `knowledge`, with `search_docs` and `get_doc`.
- **Three hosts:** a Claude Code plugin, a Hermes profile, and a terminal
  chat on the Claude Agent SDK.
- **The proof:** live conformance suites for both adapters and the
  publisher, dated read-only API probes, summaries of the live gate
  sessions, a guide to writing an adapter, and an offline test suite
  that CI runs on every push and pull request.

### Not yet run live

- The `parent` and `label` level forms, which a Plane plan without
  work-item types needs.
- `groom` under a host. Its sign-off has run, but only from a developer
  session.
- Jira below Premium.
- The `publish-docs.yml` workflow.

### Known issues

- On Plane, `find_items` returns every item's `fields` empty. `get_item`
  reads the values.
- On Plane, `get_item` by key, such as `WEB-12`, reports no iteration.
  By id, and in `find_items`, the iteration is there.
- Each board paces its own calls, so two boards on one token can reach
  the tracker's rate limit twice as fast.
- "Today" is the machine's local date, while iteration dates are read in
  the board's time zone, so near midnight the two can differ by a day.

[0.1.0]: https://github.com/ChrisKornaros/agentic_administration/releases/tag/v0.1.0
