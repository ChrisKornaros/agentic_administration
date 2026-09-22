# Next session — Phase 2, step 3: the Plane adapter

Source: agentic_optimization_research `roadmap/14-agentic-administration.md`
§5 (layer 2, the adapter boundary), §9 Phase 2 row, §3.1 findings, plus
`tools/plane/API.md` (routes, Cloudflare UA, rate limits) and
`tools/plane/plane.py` (the seed). Steps 1 (`server/model.py`, PR #2) and
2 (`server/config.py` + `examples/boards/plane.example.toml`) are merged;
trust the roadmap over this note if they disagree.

**Branch:** `feat/phase2-plane-adapter`

## Build

1. **Adapter interface** (`adapters/base.py`): the eight domain operations
   the MCP server will call (`describe_board`, `find_items`, `create_item`,
   `update_item`, `add_comment`, `create_iteration`, `move_to_iteration`,
   `close_iteration`), each in canonical-model terms; a `Capabilities`
   property; **no delete**. Plus the error taxonomy the design defers to
   here: auth, not-found, validation (incl. Plane hierarchy write errors —
   Phase 1 found no pre-check surface), rate-limit / Cloudflare wall,
   transport.
2. **Plane adapter** (`adapters/plane/`): on the `work-items` /
   `work-item-types` routes (the SDK's names), seeded from `plane.py` —
   keep its explicit `USER_AGENT`, the `X-API-Key` header, lazy secret
   resolution through one boundary (`BoardConfig.connection.token_env`,
   optionally a Bitwarden item), ~1.5–2 s throttle. `describe_board` =
   `features` + `work-item-types` + `states` + `members-lite`, and it
   validates the `BoardConfig` against the live board **before any write**
   (missing state name / type / review label → abort).
3. **Markdown → Plane HTML** renderer for descriptions (stdlib only).
4. Offline tests with recorded/faked responses; nothing live in `tests/`.

## First live read (the step-3 gate, read before write)

Run `describe_board` against the throwaway project `agentic_administration`
(created 2026-09-22, Hierarchy off) and record its type ids, states,
features and the `needs-review` label in a real (gitignored) board config.
Expect **no Bug type** — provisioning it (`POST work-item-types`) is the
first write, and the first conformance case after it is the `external_id`
write + search round-trip (step 4).

Secret handoff that worked this session: Chris writes the session key to
`~/.cache/bw_session` (`umask 077; bw unlock --raw > ~/.cache/bw_session`);
run live commands as `BW_SESSION=$(cat ~/.cache/bw_session) …` and never
print it. The seed CLI dir for `PLANE_CLI_DIR` is
`~/.cache/agentic_optimization_research/tools/plane`.

## Open questions to settle in the PR

- Where real board configs live and how they're ignored (`boards/*.toml`
  with `!*.example.toml`?) — none exist yet.
- Whether `project` in `[connection]` accepts the human identifier (`AA`)
  or only the UUID; the API retrieves by `{IDENT}-{seq}` so both may work.
- Whether `PATCH …/projects/{pid}/features` can flip `epics` (Phase 2
  conformance case; API.md says UI-only).
