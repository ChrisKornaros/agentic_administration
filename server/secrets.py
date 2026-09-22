"""The single secret boundary (design: modules/secrets-no-plaintext).

Adapters ask `get(name)` for a credential and nothing else in the codebase
reads one. Resolution order for a secret named `NAME`:

  1. `NAME` already in the environment (CI, an explicit export).
  2. Otherwise, when `NAME_BW_ITEM` names a Bitwarden vault item, the value
     is fetched via the `bw` CLI: that item's *password* field by default,
     or the custom field named by `NAME_BW_FIELD`. The vault must be
     unlocked (`BW_SESSION`, e.g. `export BW_SESSION=$(bw unlock --raw)`).

Resolution is lazy — callers pass `lambda: get("PLANE_API_KEY")` to a
transport and the lookup happens on the first real request, so anything
that never reaches the network (help text, dry runs, offline tests) never
touches Bitwarden. The value is returned to the caller and never logged,
printed or written to disk here; error messages name the *variable*, not
the value.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Callable

# Injectable for tests: (argv) -> (returncode, stdout, stderr). Never
# construct a real `bw` call from a test.
Runner = Callable[[list[str]], tuple[int, str, str]]


class SecretUnavailable(RuntimeError):
    """The named secret could not be resolved; the message never holds a value."""


def _run(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def get(name: str, *, environ: os._Environ[str] | dict[str, str] | None = None, runner: Runner = _run) -> str:
    """Return the secret called `name`; raise `SecretUnavailable` otherwise."""
    env = os.environ if environ is None else environ
    value = (env.get(name) or "").strip()
    if value:
        return value
    item_ref = (env.get(f"{name}_BW_ITEM") or "").strip()
    if not item_ref:
        raise SecretUnavailable(
            f"{name} is not set. Export it, or name the Bitwarden item that holds it "
            f"in {name}_BW_ITEM (and the custom field in {name}_BW_FIELD if it is "
            "not the password)."
        )
    return _from_bitwarden(name, item_ref, (env.get(f"{name}_BW_FIELD") or "").strip(),
                           (env.get("BW_SESSION") or "").strip(), runner)


def _from_bitwarden(name: str, item_ref: str, field: str, session: str, runner: Runner) -> str:
    if runner is _run and not shutil.which("bw"):
        raise SecretUnavailable(
            f"{name}_BW_ITEM is set but the Bitwarden `bw` CLI is not on PATH "
            "(brew install bitwarden-cli), or export the value directly."
        )
    argv = ["bw", "get", "item", item_ref, "--nointeraction"]
    if session:
        argv += ["--session", session]
    code, out, err = runner(argv)
    if code != 0:
        msg = (err or out).strip() or "unknown error"
        hint = ""
        if not session or "locked" in msg.lower() or "session" in msg.lower():
            hint = " — unlock the vault first: export BW_SESSION=$(bw unlock --raw)"
        raise SecretUnavailable(f"`bw get item {item_ref}` failed: {msg}{hint}")
    try:
        item = json.loads(out)
    except json.JSONDecodeError as exc:
        raise SecretUnavailable(f"`bw get item {item_ref}` returned non-JSON output") from exc
    if field:
        value = next((f.get("value") for f in item.get("fields") or [] if f.get("name") == field), None)
        where = f"custom field {field!r}"
    else:
        value = (item.get("login") or {}).get("password")
        where = "login password"
    value = (value or "").strip()
    if not value:
        raise SecretUnavailable(f"Bitwarden item {item_ref!r} has no {where} for {name}")
    return value
