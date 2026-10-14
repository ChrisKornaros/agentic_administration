# agentic_administration — agent contract

<!-- A map, not the territory (modules/claude-md-as-map). The eager chain here is
     ~/.claude/CLAUDE.md + ~/vault/CLAUDE.md + this file, so this file's budget is
     ~85 lines. Detail belongs in modules/, skills, and the linked docs. -->

A tracker-agnostic backlog agent: an MCP server, skills and an intake schema
over a canonical work-item model, with one adapter per tracker (Plane, and
Jira Cloud from Phase 5). Python ≥ 3.12 with uv. Humans: [README.md](README.md).

**Design source of truth:** AOR
[roadmap/14](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/roadmap/14-agentic-administration.md)
(decisions D1–D10, phases §9). Start each session from
[.claude/next-session.md](.claude/next-session.md) (surfaced by the global
SessionStart hook); where it disagrees with the roadmap, the roadmap wins.

## Composed modules

Vendored under [modules/](modules/); versions and local overrides in
[MODULES.md](MODULES.md). Skills live in [.claude/skills/](.claude/skills/) ([SKILLS.md](SKILLS.md)).

| Family | Modules | Why here |
|---|---|---|
| Git flow | [git-flow-no-direct-main](modules/git-flow-no-direct-main/index.md), [git-flow-branch-naming](modules/git-flow-branch-naming/index.md), [git-flow-session-end](modules/git-flow-session-end/index.md), [auto-commit-on-branch-done](modules/auto-commit-on-branch-done/index.md), [ask-merged-via-popup](modules/ask-merged-via-popup/index.md) | One branch = one PR; Chris merges in the GitHub UI |
| Sessions | [session-handoff](modules/session-handoff/index.md), [phase-kickoff](modules/phase-kickoff/index.md) | A phased build spanning many sessions |
| Verify | [smoke-before-commit](modules/smoke-before-commit/index.md), [verifiable-goal-before-code](modules/verifiable-goal-before-code/index.md) | `uv run pytest` gates every commit; name the check before coding |
| Integration | [secrets-no-plaintext](modules/secrets-no-plaintext/index.md), [external-api-adapter-boundary](modules/external-api-adapter-boundary/index.md), [no-live-external-in-tests](modules/no-live-external-in-tests/index.md) | The product *is* a token-authenticated adapter layer over tracker APIs |
| Scope | [stay-in-project-tree](modules/stay-in-project-tree/index.md), [no-sudo-as-shortcut](modules/no-sudo-as-shortcut/index.md) | Shell access; the denies live in `.claude/settings.json` |
| Toolchain | [python-uv-only](modules/python-uv-only/index.md), [no-cat-head-via-bash](modules/no-cat-head-via-bash/index.md) | uv for everything; Read, not `cat` |
| Docs | [claude-md-as-map](modules/claude-md-as-map/index.md), [docs-two-layer](modules/docs-two-layer/index.md), [status-emoji-discipline](modules/status-emoji-discipline/index.md) | README for humans, this file for agents; 🟢🟡🔴 flips ride the feature PR |
| Coding | [assumptions-before-code](modules/assumptions-before-code/index.md), [minimum-code-first](modules/minimum-code-first/index.md), [surgical-diffs-only](modules/surgical-diffs-only/index.md) | Per-edit discipline (experimental) |
| Preflight / review | [substrate-preflight](modules/substrate-preflight/index.md), [tight-code-review](modules/tight-code-review/index.md) | `/substrate-preflight` for new vendor surfaces (`mcp` SDK, Jira); `/tight-review` before merge |

## Session shape

Canonical loop: [git-flow-session-end](modules/git-flow-session-end/index.md), run via
`/session-wrapup`. When the branch goal is met and verified, in one response:

1. **Doc sync + hand-off, before committing:** README status/layout,
   [conformance/README.md](conformance/README.md) after a live run, this file, and
   overwrite `.claude/next-session.md` from roadmap/14 — all in the same diff.
2. **Commit → push → `gh pr create`** with the
   [Delivered + Verified](https://github.com/ChrisKornaros/agentic_optimization_research/blob/main/templates/_shared/git-workflow.md#the-delivered--verified-footer)
   footer. No "ready to commit?" stall.
3. **Merge popup** via `AskUserQuestion`: Merged · Not yet · Changes requested.
4. **Verify** `gh pr view <N> --json state,mergedAt` before any cleanup; re-pop unless `MERGED`.
5. **Clean up:** `git switch main && git pull --ff-only && git branch -d <branch> && git fetch --prune`.
6. **Memory triage:** project state → the memory store below; transferable lessons → flag for an AOR session.
7. **Print the fixed-format Session end block** (module step 6), with no guessed next step.

Per task: write "done when `<command>` shows `<result>`" before coding.

## Project rules

- **Verify:** `uv sync`, then `uv run pytest`, which is offline and the smoke for every commit. Live
  surfaces are [probes/](probes/) (read-only) and [conformance/](conformance/) (writes); run them
  only when the task calls for it. Live conformance asks permission.
- **No delete path, anywhere.** Work is completed or cancelled; no adapter method, server
  tool, probe or conformance case may delete.
- **Read-proven before write.** Adapter writes refuse until `describe_board` is clean; prove new
  vendor behavior with a read first; writes go only to the throwaway boards (Plane `AGADMIN`, Jira `AGADM`)
  and the throwaway Confluence space `AGKB` (Phase 6b), never a company site.
- **Secrets** resolve only via [server/secrets.py](server/secrets.py) (the env var named by
  `token_env`, or its Bitwarden item). Never print a token or `BW_SESSION`. Live runs: Chris writes
  `umask 077; bw unlock --raw > ~/.cache/bw_session`; then Plane is
  `PLANE_API_KEY_BW_ITEM=<the Plane item's id> PLANE_API_KEY_BW_FIELD=API BW_SESSION="$(cat ~/.cache/bw_session)"`,
  with the id from project memory (`plane-bitwarden-item`). The name `Plane` works too, since an
  ambiguous name now resolves to the exact match. AOR's `tools/plane/.env` no longer carries the field (2026-09-27). Jira: both `JIRA_API_TOKEN_BW_ITEM` and
  `JIRA_USER_BW_ITEM` name its one item (the email is its username: `JIRA_USER_BW_FIELD=username`).
  Confluence reuses that token on the same site, under `/wiki` (D29).
- **Board content never lands in git:** `boards/`, `probes/probe-report.json`,
  `conformance/reports/` and `transcripts/raw/` are gitignored; only `*.example` files and
  summarized `transcripts/*.md` (keys and checks, no item text) are committed.
- **Live requester runs** load this repo as a plugin from an empty directory: Chris runs
  `claude --plugin-dir <repo>` with `AGENTIC_ADMIN_BOARD` + the token env exported (plus
  `AGENTIC_ADMIN_KNOWLEDGE` for the docs) and the framing `--append-system-prompt` (exact block:
  README → Claude Code). Chris plays the requester;
  afterwards read the session JSONL under `~/.claude/projects/<cwd-key>/` and check the board read-only.
  **Through Hermes** (ms01, Docker): the `po` profile ([examples/hermes/](examples/hermes/) with ms01's
  paths, `knowledge` included; its `.env` holds the Plane key, the bot token and the Jira token + email),
  in the bot's Discord channel. Afterwards read the
  session from `~/.hermes/profiles/po/state.db` (open it `mode=ro`), and read the board back with `get_item`
  run inside the container (`docker exec --user hermes`, po's venv and `.env`).
  **Through the Agent SDK:** `uv run --group agent-sdk python examples/agent-sdk/chat.py` from the repo
  (it makes its own empty working directory), with the board env plus a metered `ANTHROPIC_API_KEY`
  or `ANTHROPIC_API_KEY_BW_ITEM`, never a claude.ai login. The transcript is `<session id>.jsonl`
  under `~/.claude/projects/`, with the id printed at start. Offline, point `ANTHROPIC_BASE_URL` at a
  local stub to capture the exact request (model, tools, system prompt) without spending anything.
- **Dependencies:** one runtime dependency, the official `mcp` SDK, pinned `>=2.2,<3` (v2: `MCPServer`,
  not `FastMCP`). The model, config, intake schema and adapters stay stdlib-only. Every new runtime dependency
  needs its reason in the PR plus a `/substrate-preflight`. `claude-agent-sdk` (`>=0.2.160,<0.3`) is
  not one: it is the optional `agent-sdk` dependency group, for the example alone.
- **Layering:** adapters stay mechanical ([adapters/base.py](adapters/base.py)). Conventions (the review
  label, `external_id` = `intake_id[/part]`, propose → commit with a 30-minute token, title-case
  warnings, the template fill) live in [server/service.py](server/service.py); [server/mcp_app.py](server/mcp_app.py) only
  registers the 11 tools. The SDK runs sync tools in threads, so the service serializes adapter calls.
  One server serves many boards (D43, inferred, for AOR): `Boards` holds a `BoardService` per board, named by
  its file stem, and every tool takes `board` (optional with one). With several, `describe_board()` lists them
  from the configs, any other call without one refuses, and a token never commits on another board. The
  skills ask which board unless the request names it (Chris, 2026-10-09).
  The docs are a second server (D27), never board tools: [knowledge/mcp_app.py](knowledge/mcp_app.py)
  registers `search_docs` / `get_doc` over [knowledge/docs.py](knowledge/docs.py), same pattern.
- **Public-bound (D9):** MIT, public at Phase 7. No company names or company data in code, docs,
  fixtures or commits.
- **Git:** `main` only; `feat/phase<N>-<slug>` (one PR per phase step), `chore/<slug>`,
  `docs/<slug>`. AOR changes are separate PRs in AOR.
- **Memory:** `~/vault/claude/memory/agentic_administration/`, symlinked per machine from
  `~/.claude/projects/<key>/memory`. The vault's hooks commit it; never commit it from here.
- **`plane-board-ops`** drives AOR's `tools/plane/plane.py`, not this repo's adapter.

## Layout

| Path | Role |
|---|---|
| [server/](server/) | Canonical model, board config, secrets; the MCP server (`python -m server <board.toml or boards/>`, stdio; a directory serves each `*.toml` with a `backend`, and skips the rest, such as docs configs) |
| [schema/](schema/) | The intake record (one request → its parts) and its Markdown rendering; `propose_item(intake=…, part=…)` consumes it |
| [skills/](skills/) | The **product** skills (public): `intake` (its context step, and only it, also calls `search_docs` → `get_doc` where the host has them), `create-story` / `create-bug` / `create-epic`, `plan-sprint` (rollover: one yes, then close → create → move), `plan-cycle` (a cycle from the templates' `days` cadence: one yes on the exact write-up, then cycle → epic → each slot under it → read-back; ids `<first day>-cycle/<template>-<date>`, so a rerun finds what landed; intake sends a dated piece there), `groom` (the review queue via `find_items(label=…)`; one yes, then a fresh `get_item` before each `update_item`). Not the dev skills in `.claude/skills/`. Frontmatter is `name` + `description` only, and tools are named bare because hosts prefix them. [tests/test_skills.py](tests/test_skills.py) ties them to the 11 + 2 tools, the tools' arguments and the schema |
| [adapters/](adapters/) | `base.py` interface + error taxonomy; `plane/` and `jira/` adapters (`jira/adf.py`: Markdown ↔ ADF, tables included, shared with Confluence) |
| [knowledge/](knowledge/) | Phase 6b, stdlib only: `python -m knowledge publish <dir> --config <toml>`, a dry run unless `--apply`. It publishes Markdown → Confluence pages over the Jira transport (`confluence.py` is the only file that knows the wire) and finds its pages by the `md-source` property, both under the configured parent and by CQL label, since the search index lags; a page counts only if it carries the label (one label per tree; trees may share a parent). No DELETE: the classic token can delete (D29), so [tests/test_knowledge.py](tests/test_knowledge.py) scans for one. `python -m knowledge serve --config <toml>` is the `knowledge` MCP server (step 4, [tests/test_docs.py](tests/test_docs.py)): the same TOML, scoped to its space + label, CQL `siteSearch` (ranked; `text ~` isn't), `get_doc` refusing any page outside that scope; an empty `--config` serves no tools |
| [.claude-plugin/](.claude-plugin/) | `plugin.json`: `skills/` + two servers as a Claude Code plugin: `board` (from `AGENTIC_ADMIN_BOARD`) and `knowledge` (from `${AGENTIC_ADMIN_KNOWLEDGE:-}`; the `:-` matters, since an unset variable fails a plugin server, and empty means no tools). Inline `mcpServers`, not a root `.mcp.json`, which would also load in dev sessions |
| [conformance/](conformance/) | Live adapter suite + dated results; `knowledge.py` is the publisher's live suite (`python -m conformance.knowledge <kb.toml>`: a fresh, empty parent page per run id, one stop for a person to archive the orphan) |
| [probes/](probes/) | Dated read-only API evidence |
| [transcripts/](transcripts/) | Dated summaries of live gate sessions (Phases 3, 4, 6 and 6c, the 6b read gate, the Hermes docs run, and the first real-board run on Food Content) |
| [tests/](tests/) | Offline unit tests (`fake_plane.py`, `fake_jira.py`, `fake_confluence.py` transports) |
| [examples/boards/](examples/boards/) | The committed board-config templates (Plane, Jira, and a calendar board). `board_type` (D38): a `calendar` board may leave `bug` out (capabilities report it `absent`) and has review off unless it names `labels.review` (D39, D40). `[fields]` (D41) maps a name to a Plane work-item property or a Jira `customfield_*` (on Jira, only once it is on a screen); items carry `start_date` / `target_date` (Jira: "Start date" by name, `duedate`). `[templates.<name>]` (D41, D42): level, feature, labels, fields, state, a `{month}` `{year}` title pattern, a skeleton whose `{description}` takes the request's text, and the `days` + `dates` cadence, used by `propose_item(template=…)`; [tests/test_config.py](tests/test_config.py) loads every example |
| [examples/knowledge/](examples/knowledge/) | The publisher's config template (site, space, parent page, label, write cap); the real one goes in gitignored `boards/`. `publish-docs.yml`: the publish-on-push GitHub Actions job, tied to the CLI and the template by [tests/test_knowledge.py](tests/test_knowledge.py) |
| [examples/hermes/](examples/hermes/) | Hermes reference wiring: a profile `config.fragment.yaml` (stdio servers: `board` over `boards/` with every backend's token and the 11-tool include, so one profile serves every board; an optional `knowledge` with the 2; skills in place, `write_approval`) + `SOUL.md` (the framing line). [tests/test_examples.py](tests/test_examples.py) ties both to the tools and the README |
| [examples/agent-sdk/](examples/agent-sdk/) | The Agent SDK terminal chat (`chat.py`): the repo as a plugin, the framing line, `tools=["Skill"]` + the 11 board tools and the 2 docs tools only, no settings sources or claude.ai connectors, reads unasked and each write behind a `y`. [tests/test_examples.py](tests/test_examples.py) reads its constants by AST (the SDK is optional) and ties them to the servers' read-only annotations, SOUL.md and the README's `--allowedTools` (`${T}` board, `${K}` docs) |
