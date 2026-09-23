# Next session — Phase 3: the domain MCP server + intake / create-* skills

Source: agentic_optimization_research `roadmap/14-agentic-administration.md`,
specifically the §9 Phase 3 row, §5 layer 3 (the small domain MCP server,
about eight tools, conventions and no-delete *enforced as behavior*), §7
(intake schema + confirm flow), D5 (propose-then-confirm) and §11 (the
review label is the server's job, answered 2026-09-22). If the roadmap
and this note disagree, trust the roadmap.

**Gate:** a requester-style transcript in a Claude Code session against
Plane produces a correctly placed story with acceptance criteria and the
review label.

Phase 2 closed 2026-09-22 (this repo's `feat/phase2-conformance` PR +
AOR PR #210). The Plane adapter passes conformance 9/9 live;
`conformance/README.md` has the findings.

## Suggested shape — one PR per step, like Phase 2

1. **`server/` MCP server** (`feat/phase3-mcp-server`): the eight tools
   of §5 over `adapters.base.Adapter`, built from a board config. Server
   behaviour, not adapter behaviour:
   - add `labels.review` on every create (§11; the adapter stays
     mechanical);
   - derive `external_id` from the intake record id, so a retried create
     is found, not duplicated;
   - map `AdapterError` subclasses to tool errors the agent can act on
     (`ConfigMismatch` → "fix the board config"; `RateLimited` /
     `Blocked` → "wait, then retry");
   - expose no delete, by construction.
2. **`schema/` intake schema** (§7 fields: problem, outcome,
   constraints, urgency, related, acceptance as Given/When/Then,
   proposed_placement), plus its Markdown rendering into the item
   description.
3. **`skills/`**: `intake`, `create-story` / `create-bug` /
   `create-epic` (decomposition, then placement from `describe_board`,
   then confirm).
4. **The gate transcript**: a Claude Code session with the server
   plugged in, against `boards/agentic_administration.toml` (AGADMIN).

## Open questions to settle first

- **MCP dependency.** The runtime is standard-library only
  (`pyproject.toml`: "anything added here needs a reason in the PR").
  The choice is the official `mcp` Python SDK (protocol correctness,
  the first runtime dependency) or hand-rolled stdio JSON-RPC.
  Recommend the SDK, with the reason written in the PR. Run
  `/substrate-preflight` on it.
- **Where "confirm" lives (D5, `confirm = "always"`).** Options: a
  two-step tool (propose returns a token, commit takes it), or a
  `confirmed: true` argument the skill sets only after the requester
  says yes. The server should enforce it, not just the prompt.
- **Expose `get_item` / `get_iteration` as tools?** They are adapter
  reads beyond the eight; the skills likely need `get_item` for "file
  it under AGADMIN-1".
- `naming.item_case` (title case) is validated in config but enforced
  nowhere yet. Should the server check it?

## Carry-over facts

- Board: `AGADMIN` (throwaway) is fully provisioned: Epic/Story/Bug/Task
  types, labels `needs-review bug feature chore docs`, module
  `Conformance 20260922`, cycles `202609` (closed) and `202610`, items
  AGADMIN-1 to AGADMIN-5. The real config is
  `boards/agentic_administration.toml` (gitignored).
- Plane wire facts now encoded in the adapter: every route ends in `/`;
  the external_id lookup is the project list (one record or a 404);
  single-item reads return label objects; cycles carry no `status`, and
  their dates are read in the project timezone.
- Conformance: the date-parsing fix landed after the live 9/9 run and
  was verified read-only. The next full run (a new `--run-id`, ideally
  in October so the month has an open iteration) exercises it end to
  end.

## Secret handoff that works

Chris writes the session key with
`umask 077; bw unlock --raw > ~/.cache/bw_session`. Run live commands with
the sibling AOR `tools/plane/.env` exported, plus
`PLANE_API_KEY_BW_ITEM="$PLANE_BW_ITEM" PLANE_API_KEY_BW_FIELD="$PLANE_BW_FIELD"
BW_SESSION="$(cat ~/.cache/bw_session)"`. Never print any of them.
