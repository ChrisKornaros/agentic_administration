"""The single secret boundary (design: modules/secrets-no-plaintext).

Adapters ask `get(name)` for a credential and nothing else in the codebase
reads one. Resolution order for a secret named `NAME`:

  1. `NAME` already in the environment (CI, an explicit export).
  2. Otherwise, when `NAME_BW_ITEM` names a Bitwarden vault item, the value
     is fetched via the `bw` CLI: that item's *password* field by default,
     its login *username* when `NAME_BW_FIELD` is `username` (Jira's
     account email sits next to its token), or else the custom field named
     by `NAME_BW_FIELD`. The vault must be unlocked (`BW_SESSION`, e.g.
     `export BW_SESSION=$(bw unlock --raw)`). The item is an id or a name;
     a name that several items match resolves to the one named exactly that.

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
    code, out, err = runner(_bw(["get", "item", item_ref], session))
    msg = (err or out).strip() or "unknown error"
    if code != 0 and "more than one result" in msg.lower():
        item = _named_exactly(item_ref, session, runner)
    elif code != 0:
        hint = ""
        if not session or "locked" in msg.lower() or "session" in msg.lower():
            hint = " — unlock the vault first: export BW_SESSION=$(bw unlock --raw)"
        raise SecretUnavailable(f"`bw get item {item_ref}` failed: {msg}{hint}")
    else:
        item = _json(out, f"`bw get item {item_ref}`")
    if field == "username":
        value = (item.get("login") or {}).get("username")
        where = "login username"
    elif field:
        value = next((f.get("value") for f in item.get("fields") or [] if f.get("name") == field), None)
        where = f"custom field {field!r}"
    else:
        value = (item.get("login") or {}).get("password")
        where = "login password"
    value = (value or "").strip()
    if not value:
        raise SecretUnavailable(f"Bitwarden item {item_ref!r} has no {where} for {name}")
    return value


def _bw(args: list[str], session: str) -> list[str]:
    return ["bw", *args, "--nointeraction", *(["--session", session] if session else [])]


def _json(out: str, what: str):
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise SecretUnavailable(f"{what} returned non-JSON output") from exc


def _named_exactly(item_ref: str, session: str, runner: Runner) -> dict:
    """`bw get item` refuses a name that several items match (its search is a
    substring one); take the one item named exactly `item_ref`."""
    code, out, err = runner(_bw(["list", "items", "--search", item_ref], session))
    if code != 0:
        raise SecretUnavailable(f"`bw list items --search {item_ref}` failed: {(err or out).strip() or 'unknown error'}")
    exact = [i for i in _json(out, f"`bw list items --search {item_ref}`") if i.get("name") == item_ref]
    if len(exact) != 1:
        raise SecretUnavailable(f"several Bitwarden items match {item_ref!r} and {len(exact)} of them "
                                "is named exactly that; name the item by its id instead")
    return exact[0]
