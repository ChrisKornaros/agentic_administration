---
name: python-uv-only
type: guardrail
scope: repo
lifecycle: stable
dependencies: []
evidence:
  - tools-stack/ops.md
  - case-studies/product-use-tracker/playbook.md
  - roadmap/06-tech-stack-defaults.md
applies_when:
  - project is Python
  - host hasn't explicitly opted into a different toolchain
version: 1
---

# Python — `uv` only, never `pip`/`poetry`/`pdm`

## Rule

Use [`uv`](https://docs.astral.sh/uv/) as the sole Python environment
and dependency manager. Add deps with `uv add`, run code with
`uv run`, lock with `uv lock`. Do not invoke `pip`, `pip install`,
`pipx`, `poetry`, `pdm`, `virtualenv`, or `python -m venv` in this
repo — not in scripts, not in CI, not in setup docs, not "just this
once" to install a one-off package.

## Why

Reproducibility across machines (laptop ↔ Pi) requires a locked,
single-source-of-truth manifest. `uv` is fast, manages Python
interpreters too, ships a real lockfile (`uv.lock`) that pins
transitive deps with hashes, and works identically on macOS dev and
Linux deploy — see
[tools-stack/ops.md](../../tools-stack/ops.md) (the `uv run` reference
under §Alternative: systemd / launchd) and the
[product-use-tracker smoke pattern](../../case-studies/product-use-tracker/playbook.md)
that runs `uv run python app.py` in CI.

Mixing `pip install` into a `uv`-managed project silently bypasses
the lockfile — the dep is present on the machine where it was run,
absent everywhere else, and the divergence isn't caught until
deploy. The failure mode is "works on my laptop, breaks on the Pi,"
which is exactly what the lockfile was supposed to prevent.

## How to apply

- **First setup of a new repo:** `uv init` (or `uv venv` for a
  bare env). Do not `python -m venv .venv`.
- **Adding a dependency:** `uv add <pkg>`. Commit the updated
  `pyproject.toml` and `uv.lock` together.
- **Running anything:** `uv run <cmd>` — Python scripts, `pytest`,
  `ruff`, one-off REPL sessions. `uv run` resolves the env from
  the lockfile every time.
- **Scripts and CI:** smoke scripts, `Makefile` targets, and
  GitHub Actions invoke tools via `uv run`, never via a bare
  `python`/`pytest` that depends on global state.
- **If a tool needs a global install** (e.g. `ruff` for editor
  integration): use `uv tool install <pkg>`, not `pipx`.
- **Refuse the `pip install` shortcut.** If a Stack Overflow
  answer or library README suggests `pip install foo`, translate
  to `uv add foo` before running it.

## Anti-patterns

- `pip install -r requirements.txt` "to get going quickly" — the
  lockfile is the source of truth; `requirements.txt` shouldn't
  exist in a `uv` project.
- `python -m venv .venv && source .venv/bin/activate && pip
  install ...` — same problem, longer form.
- Mixing `poetry add` into a `uv` project (or vice versa). Pick
  one; this repo picks `uv`.
- Committing a `pip`-produced `requirements.txt` alongside
  `uv.lock`. The two diverge silently.
- A `Dockerfile` `RUN pip install` step that bypasses the
  lockfile inside the container build.

## Related

- [[duckdb-default-store]]
- [[deploy-target-arch]]
