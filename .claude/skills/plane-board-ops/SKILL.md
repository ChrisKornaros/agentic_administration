---
name: plane-board-ops
description: "Drives a Plane board through the repo-owned CLI following Chris's conventions — YYYYMM cycles, roadmap/calendar epics, repo-area/category modules, no-delete (Complete-or-Cancel) discipline. Use when creating, updating, or organizing issues, cycles, epics, or modules on a Plane board."
version: 1.0.0
source: tools/plane/CONVENTIONS.md
tags: [plane, project-management, po-agent, agentic-optimization-research]
---

# Plane board ops

Use before creating or changing work on a Plane board via
`uv run tools/plane/plane.py …`. It loads the board model so structure and
naming stay consistent, and enforces the no-delete discipline.

## The model (apply it)

- **Cycles are always `YYYYMM`** (`202606`). Uniform time-boxing on every
  board; *epics* carry the roadmap/calendar meaning, not cycles.
- **Epics** = the big buckets. *Calendar* projects: one per month
  (`February 2026 Content`) + standing sub-deliverable epics (`Recipe
  Site`). *Roadmap* projects (code repos like AOR): one per `roadmap/0X`
  target. Epics are now a **work-item type** (`is_epic: true`), dual-served
  at `/issues/` and `/epics/`.
- **Stories** = the unit of work, nested under their epic via `parent`.
- **Tasks** = only when a Story must be split — child of a Story, never
  top-level.
- **Modules** = a cross-cutting grouping: content **category** on calendar
  boards (`Baking Videos`), repo **subdirectory** on code boards (`tools`,
  `agents`, `hosts`).
- **Naming:** project identifier ALL CAPS; cycle `YYYYMM`; every work item
  Proper Case Like This.
- **Labels:** one standardized set per project *kind* — code → `bug`/
  `feature`/`chore`/`docs`; content → `video`/`picture`/`blog`; personal
  tracking → the stream. Don't carry initiative labels into a project.

## The no-delete rule (hard)

- **Never delete.** The CLI has no delete path by design — don't add one,
  don't reach for the API directly to remove an item.
- **Complete or Cancel** instead: finished → `Done`, abandoned →
  `Cancelled`. Both are terminal and kept, so the board records what was
  done *and* dropped (`issues update --state-name Done|Cancelled`).
- **To revisit done/cancelled work, create a *new* item and link back** —
  don't reopen. Each past item stays a stable, trackable artifact.

## Before you write

- **Prove the matching `list` read live first** for any surface
  ([tools/plane/CLAUDE.md](../../tools/plane/CLAUDE.md) rule 2).
- Resolve state/label/assignee **names → UUIDs** via `states list` (the
  write body takes UUIDs, not names).

Full model + the worked Food Content example:
[tools/plane/CONVENTIONS.md](../../tools/plane/CONVENTIONS.md).
