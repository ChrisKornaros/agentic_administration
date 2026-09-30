# Vendored modules

Pulled from [agentic_optimization_research/modules/](https://github.com/ChrisKornaros/agentic_optimization_research/tree/main/modules).
When a module's canonical version bumps, re-copy and update the row here. Local overrides go in the **Override** column.

| Module | Version | Source commit | Copied at | Override |
|---|---|---|---|---|
| [git-flow-no-direct-main](modules/git-flow-no-direct-main/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [git-flow-branch-naming](modules/git-flow-branch-naming/index.md) | 1 | `bee8f3c` | 2026-09-23 | Phase branches are `feat/phase<N>-<slug>` (numbered phases 0–7 of AOR roadmap/14, one PR per phase step), not `feat/phase-<a-g>-<slug>` |
| [git-flow-session-end](modules/git-flow-session-end/index.md) | 5 | `bee8f3c` | 2026-09-23 | Stop guard + `gh pr create` nudge run from the global dotfiles `~/.claude/settings.json`, not this repo's settings (would double-fire) |
| [auto-commit-on-branch-done](modules/auto-commit-on-branch-done/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [ask-merged-via-popup](modules/ask-merged-via-popup/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [smoke-before-commit](modules/smoke-before-commit/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [session-handoff](modules/session-handoff/index.md) | 3 | `bee8f3c` | 2026-09-23 | Kickoff is drawn from AOR roadmap/14 (another repo). Transferable lessons are flagged for an AOR session, not written into AOR from here. SessionStart hook runs from the global dotfiles |
| [phase-kickoff](modules/phase-kickoff/index.md) | 1 | `bee8f3c` | 2026-09-23 | The phase doc is AOR roadmap/14 §9 (external), not a file in this repo |
| [claude-md-as-map](modules/claude-md-as-map/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [docs-two-layer](modules/docs-two-layer/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [status-emoji-discipline](modules/status-emoji-discipline/index.md) | 1 | `bee8f3c` | 2026-09-23 | README's Layout tree keeps its in-place `✅ = exists` legend (a presence marker, not a status table) |
| [secrets-no-plaintext](modules/secrets-no-plaintext/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [external-api-adapter-boundary](modules/external-api-adapter-boundary/index.md) | 2 | `468facd` | 2026-09-29 | — |
| [no-live-external-in-tests](modules/no-live-external-in-tests/index.md) | 1 | `bee8f3c` | 2026-09-23 | `probes/` (read-only) and `conformance/` (writes to a throwaway board) are live by design; they are not tests and never run from `tests/` |
| [stay-in-project-tree](modules/stay-in-project-tree/index.md) | 2 | `468facd` | 2026-09-29 | Live runs export the sibling AOR `tools/plane/.env` (Plane key pointers) and read `~/.cache/bw_session`: the sanctioned out-of-tree reads. Phase 4 (Hermes, on ms01) also writes the `po` profile's `config.yaml` + `SOUL.md` under `~/.hermes/profiles/po/` and the read-only repo mount in `~/hermes-agent/docker-compose.override.yml`, runs `docker exec hermes …`, and reads the Hermes source and docs in `~/hermes-agent` and the gate session from po's `state.db` (read-only); the profile's `.env` and the container recreate stay Chris's |
| [no-sudo-as-shortcut](modules/no-sudo-as-shortcut/index.md) | 2 | `468facd` | 2026-09-29 | — |
| [python-uv-only](modules/python-uv-only/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [no-cat-head-via-bash](modules/no-cat-head-via-bash/index.md) | 1 | `bee8f3c` | 2026-09-23 | Re-read guard runs from the global dotfiles (the H2 experiment copy), not this repo's settings (would double-fire) |
| [substrate-preflight](modules/substrate-preflight/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [assumptions-before-code](modules/assumptions-before-code/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [minimum-code-first](modules/minimum-code-first/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [surgical-diffs-only](modules/surgical-diffs-only/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [verifiable-goal-before-code](modules/verifiable-goal-before-code/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
| [tight-code-review](modules/tight-code-review/index.md) | 1 | `bee8f3c` | 2026-09-23 | — |
