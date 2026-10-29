# Vendored skills

Pulled from [agentic_optimization_research/skills/](https://github.com/ChrisKornaros/agentic_optimization_research/tree/main/skills).
Each skill is a thin SKILL.md shim, vendored into `.claude/skills/<name>/` — auto-paired with the module it backs, or added standalone. Local overrides go in the **Override** column.

| Skill | Version | Source commit | Copied at | Backs module | Override |
|---|---|---|---|---|---|
| [session-wrapup](.claude/skills/session-wrapup/SKILL.md) | 1.3.0 | `80cb228` | 2026-10-29 | git-flow-session-end | — |
| [session-start](.claude/skills/session-start/SKILL.md) | 1.1.0 | `80cb228` | 2026-10-29 | session-handoff | — |
| [phase-kickoff](.claude/skills/phase-kickoff/SKILL.md) | 1.0.0 | `80cb228` | 2026-10-29 | phase-kickoff | — |
| [substrate-preflight](.claude/skills/substrate-preflight/SKILL.md) | 1.0.0 | `80cb228` | 2026-10-29 | substrate-preflight | — |
| [tight-review](.claude/skills/tight-review/SKILL.md) | 1.0.0 | `80cb228` | 2026-10-29 | tight-code-review | — |
| [scope-guard](.claude/skills/scope-guard/SKILL.md) | 1.0.0 | `80cb228` | 2026-10-29 | — | — |
| [constraint-check](.claude/skills/constraint-check/SKILL.md) | 1.0.0 | `80cb228` | 2026-10-29 | — | — |
| [minimal-repro](.claude/skills/minimal-repro/SKILL.md) | 1.0.0 | `80cb228` | 2026-10-29 | — | — |
| [explain-back](.claude/skills/explain-back/SKILL.md) | 1.0.0 | `80cb228` | 2026-10-29 | — | — |
| [plane-board-ops](.claude/skills/plane-board-ops/SKILL.md) | 1.1.0 | `80cb228` | 2026-10-29 | — | Drives AOR's `tools/plane/plane.py` CLI (sibling repo), which this repo's `adapters/plane` supersedes per D10 |
