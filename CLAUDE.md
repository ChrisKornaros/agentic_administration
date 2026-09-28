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
  vendor behavior with a read first; writes go only to the throwaway boards (Plane `AGADMIN`, Jira `AGADM`),
  never a company site.
- **Secrets** resolve only via [server/secrets.py](server/secrets.py) (the env var named by
  `token_env`, or its Bitwarden item). Never print a token or `BW_SESSION`. Live runs: Chris writes
  `umask 077; bw unlock --raw > ~/.cache/bw_session`; then Plane is
  `PLANE_API_KEY_BW_ITEM=<the Plane item's id> PLANE_API_KEY_BW_FIELD=API BW_SESSION="$(cat ~/.cache/bw_session)"`,
  with the id from project memory (`plane-bitwarden-item`): the name `Plane` also matches
  `content_manager:plane:api_key`, and AOR's `tools/plane/.env` no longer carries the field (2026-09-27). Jira: both `JIRA_API_TOKEN_BW_ITEM` and
  `JIRA_USER_BW_ITEM` name its one item (the email is its username: `JIRA_USER_BW_FIELD=username`).
- **Board content never lands in git:** `boards/`, `probes/probe-report.json`,
  `conformance/reports/` and `transcripts/raw/` are gitignored; only `*.example` files and
  summarized `transcripts/*.md` (keys and checks, no item text) are committed.
- **Live requester runs** load this repo as a plugin from an empty directory: Chris runs
  `claude --plugin-dir <repo>` with `AGENTIC_ADMIN_BOARD` + the token env exported and the
  framing `--append-system-prompt` (exact block: README → Claude Code). Chris plays the requester;
  afterwards read the session JSONL under `~/.claude/projects/<cwd-key>/` and check the board read-only.
  **Through Hermes** (ms01, Docker): the `po` profile ([examples/hermes/](examples/hermes/) with ms01's
  paths; its `.env` holds the Plane key and bot token), in the bot's Discord channel. Afterwards read the
  session from `~/.hermes/profiles/po/state.db` (open it `mode=ro`), and read the board back with `get_item`
  run inside the container (`docker exec --user hermes`, po's venv and `.env`).
- **Dependencies:** one runtime dependency, the official `mcp` SDK, pinned `>=2.2,<3` (v2: `MCPServer`,
  not `FastMCP`). The model, config, intake schema and adapters stay stdlib-only. Every new runtime dependency
  needs its reason in the PR plus a `/substrate-preflight`.
- **Layering:** adapters stay mechanical ([adapters/base.py](adapters/base.py)). Conventions (the review
  label, `external_id` = `intake_id[/part]`, propose → commit with a 30-minute token, title-case
  warnings) live in [server/service.py](server/service.py); [server/mcp_app.py](server/mcp_app.py) only
  registers the 11 tools. The SDK runs sync tools in threads, so the service serializes adapter calls.
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
| [server/](server/) | Canonical model, board config, secrets; the MCP server (`python -m server <board.toml>`, stdio) |
| [schema/](schema/) | The intake record (one request → its parts) and its Markdown rendering; `propose_item(intake=…, part=…)` consumes it |
| [skills/](skills/) | The **product** skills (public): `intake`, `create-story` / `create-bug` / `create-epic`, `plan-sprint` (rollover: one yes, then close → create → move), `groom` (the review queue via `find_items(label=…)`; one yes, then a fresh `get_item` before each `update_item`). Not the dev skills in `.claude/skills/`. Frontmatter is `name` + `description` only, and tools are named bare because hosts prefix them. [tests/test_skills.py](tests/test_skills.py) ties them to the 11 tools and the schema |
| [adapters/](adapters/) | `base.py` interface + error taxonomy; `plane/` and `jira/` adapters (`jira/adf.py`: Markdown ↔ ADF) |
| [.claude-plugin/](.claude-plugin/) | `plugin.json`: `skills/` + the server (`board`, from `AGENTIC_ADMIN_BOARD`) as a Claude Code plugin. Inline `mcpServers`, not a root `.mcp.json`, which would also load in dev sessions |
| [conformance/](conformance/) | Live adapter suite + dated results |
| [probes/](probes/) | Dated read-only API evidence |
| [transcripts/](transcripts/) | Dated summaries of live requester sessions (the Phase 3 and Phase 4 gates) |
| [tests/](tests/) | Offline unit tests (`fake_plane.py`, `fake_jira.py` transports) |
| [examples/boards/](examples/boards/) | The committed board-config templates (Plane, Jira) |
| [examples/hermes/](examples/hermes/) | Hermes reference wiring: a profile `config.fragment.yaml` (stdio server, 11-tool include, skills in place, `write_approval`) + `SOUL.md` (the framing line). [tests/test_examples.py](tests/test_examples.py) ties both to the tools and the README |
