# agentic_administration

An agent-operated administration layer for engineering teams: turn a
request typed into a chat window into a well-formed backlog item —
epic, feature, story, bug, or task — filed under the right parent, in
the right sprint, on whatever tracker your team already runs.

> **Status: building (2026-09).** Nothing is installable yet. The
> design is settled, the first backend (Plane) passes its conformance
> suite against a live throwaway project, and the MCP server runs
> (offline-tested; its live proof comes with the skills). The intake
> schema is in; the skills are next. Watch the releases for the first
> usable version.

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
  tracker's API. Plane first; Jira Cloud (Premium/Enterprise) second;
  Azure DevOps designed-for. A parent-only generic mode covers
  trackers without typed hierarchies.
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
runtime you already operate; the repo will document a runnable Claude
Agent SDK example and a Hermes configuration as reference wirings.

## Layout (planned; ✅ = exists)

```
agentic_administration/
├── README.md
├── LICENSE            # MIT
├── CLAUDE.md          # agent context; modules/ + .claude/skills/ vendored from agentic_optimization_research  ✅
├── server/            # the MCP server + canonical model  ✅ model.py, config.py, secrets.py, service.py, mcp_app.py
├── adapters/          # plane/, jira/, ado/, generic/  ✅ base.py (interface + errors), plane/
├── boards/            # real board configs — gitignored; examples/boards/ has the template
├── skills/            # intake, create-*, plan-sprint, groom
├── schema/            # the intake schema + its Markdown rendering  ✅ intake.py (the board config schema is server/config.py)
├── conformance/       # the adapter test suite  ✅ Plane passes live
├── examples/          # board configs, an Agent SDK bot, a Hermes config  ✅ boards/
├── probes/            # dated read-only API checks (evidence)  ✅
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
`<token_env>_BW_ITEM` (custom field via `<token_env>_BW_FIELD`).

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

To prove an adapter against a **throwaway** project (real writes, never
a delete), run the conformance suite:
`uv run python -m conformance boards/<board>.toml` (add `--dry-run` to
list the cases first). See [conformance/README.md](conformance/README.md)
for the cases and the dated results.

## License

MIT — see [LICENSE](LICENSE).
