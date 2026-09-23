"""The adapter conformance suite (design: roadmap/14 D7 — a new backend is an
adapter plus this suite passing against a throwaway project).

Not under `tests/`: it talks to a live tracker and writes to it, so it
never runs in the default `uv run pytest`. Run it with
`uv run python -m conformance boards/<board>.toml`; see README.md.
"""
