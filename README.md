# agentic_administration

An agent-operated administration layer for engineering teams: turn a
request typed into a chat window into a well-formed backlog item —
epic, feature, story, bug, or task — filed under the right parent, in
the right sprint, on whatever tracker your team already runs.

> **Status: design phase (2026-09).** Nothing is installable yet. The
> design is settled; the first backend (Plane) and the tool surface are
> being built. Watch the releases for the first usable version.

## What it is

- **A small MCP server** exposing a handful of *domain* tools —
  create item, update item, comment, create iteration, move to
  iteration, close iteration, find, describe board — over a canonical
  work-item model. Your agent runtime (Claude Code, the Claude Agent
  SDK, Hermes, or any MCP-capable host) plugs it in.
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

## Layout (planned)

```
agentic_administration/
├── README.md
├── LICENSE            # MIT
├── server/            # the MCP server + canonical model
├── adapters/          # plane/, jira/, ado/, generic/
├── skills/            # intake, create-*, plan-sprint, groom
├── schema/            # the intake schema + board config schema
├── conformance/       # the adapter test suite
└── examples/          # board configs, an Agent SDK bot, a Hermes config
```

## License

MIT — see [LICENSE](LICENSE).
