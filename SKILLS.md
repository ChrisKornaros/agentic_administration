# Vendored skills

Pulled from [agentic_optimization_research/skills/](https://github.com/ChrisKornaros/agentic_optimization_research/tree/main/skills).
Each skill is a thin SKILL.md shim, vendored into `.claude/skills/<name>/` — auto-paired with the module it backs, or added standalone. Local overrides go in the **Override** column.

| Skill | Version | Source commit | Copied at | Backs module | Override |
|---|---|---|---|---|---|
| [session-wrapup](.claude/skills/session-wrapup/SKILL.md) | 1.2.0 | `bee8f3c` | 2026-09-23 | git-flow-session-end | — |
| [session-start](.claude/skills/session-start/SKILL.md) | 1.0.0 | `bee8f3c` | 2026-09-23 | session-handoff | Says the kickoff is a gitignored symlink into the private memory store, since the repo is public (2026-10-28). The canonical text still assumes a committed kickoff, so re-apply this after a `--force` re-vendor |
| [phase-kickoff](.claude/skills/phase-kickoff/SKILL.md) | 1.0.0 | `bee8f3c` | 2026-09-23 | phase-kickoff | — |
| [substrate-preflight](.claude/skills/substrate-preflight/SKILL.md) | 1.0.0 | `bee8f3c` | 2026-09-23 | substrate-preflight | — |
| [tight-review](.claude/skills/tight-review/SKILL.md) | 1.0.0 | `bee8f3c` | 2026-09-23 | tight-code-review | — |
| [scope-guard](.claude/skills/scope-guard/SKILL.md) | 1.0.0 | `bee8f3c` | 2026-09-23 | — | — |
| [constraint-check](.claude/skills/constraint-check/SKILL.md) | 1.0.0 | `bee8f3c` | 2026-09-23 | — | — |
| [minimal-repro](.claude/skills/minimal-repro/SKILL.md) | 1.0.0 | `bee8f3c` | 2026-09-23 | — | — |
| [explain-back](.claude/skills/explain-back/SKILL.md) | 1.0.0 | `bee8f3c` | 2026-09-23 | — | — |
| [plane-board-ops](.claude/skills/plane-board-ops/SKILL.md) | 1.0.0 | `bee8f3c` | 2026-09-23 | — | Drives AOR's `tools/plane/plane.py` CLI (sibling repo), which this repo's `adapters/plane` supersedes per D10; its `tools/plane/` links resolve only in AOR |
