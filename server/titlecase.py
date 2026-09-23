"""The `naming.item_case` check (design: agentic_optimization_research
roadmap/14 D14): a warning and a suggested title at propose time, never a
reject and never an auto-fix.

Conservative on purpose. Only a *plain* word — lowercase letters, maybe
wrapped in brackets, quotes or trailing punctuation — is ever
capitalized. Anything else is left exactly as written: acronyms (`API`),
mixed case (`macOS`), numbers (`v2`, `202609`), and code names
(`find_items`, `plane-board-ops`, `server/config.py`). "Title" follows
CONVENTIONS §3 ("Proper Case Like This"): every plain word, small words
included. "Sentence" capitalizes only the first word and never lowercases
anything, so proper nouns survive.
"""

from __future__ import annotations

import re

from server.config import ItemCase

_PLAIN = re.compile(r"^([(\[\"']*)([a-z]+)([)\]\"'.,:;!?]*)$")


def _capitalize(word: str) -> str:
    m = _PLAIN.match(word)
    if m is None:
        return word
    lead, letters, trail = m.groups()
    return f"{lead}{letters[0].upper()}{letters[1:]}{trail}"


def suggest(title: str, case: ItemCase) -> str | None:
    """The title `case` asks for, or None when `title` already fits (or
    there is no rule)."""
    if case is ItemCase.ANY:
        return None
    parts = re.split(r"(\s+)", title)  # keep the original spacing
    words = [i for i, p in enumerate(parts) if p and not p.isspace()]
    targets = words if case is ItemCase.TITLE else words[:1]
    for i in targets:
        parts[i] = _capitalize(parts[i])
    fixed = "".join(parts)
    return fixed if fixed != title else None
