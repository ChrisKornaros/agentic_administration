"""The conservative title-caser behind `naming.item_case` (roadmap/14 D14)."""

import pytest

from server.config import ItemCase
from server.titlecase import suggest


@pytest.mark.parametrize(
    "title, fixed",
    [
        ("add retry to find_items", "Add Retry To find_items"),
        ("Requester Can File A Bug", None),
        ("fix macOS keychain lookup via API", "Fix macOS Keychain Lookup Via API"),
        ("09 — plane PM substrate", "09 — Plane PM Substrate"),
        ("bump to v2 (the new sdk)", "Bump To v2 (The New Sdk)"),
        ("read-only mode for server/config.py", "read-only Mode For server/config.py"),
        ("keep  double  spaces", "Keep  Double  Spaces"),
    ],
)
def test_title_case_capitalizes_plain_words_only(title, fixed):
    assert suggest(title, ItemCase.TITLE) == fixed


@pytest.mark.parametrize(
    "title, fixed",
    [
        ("add retry to Plane", "Add retry to Plane"),
        ("Add Retry To Plane", None),  # sentence case never lowercases: proper nouns survive
        ("macOS keychain lookup", None),
    ],
)
def test_sentence_case_only_touches_the_first_word(title, fixed):
    assert suggest(title, ItemCase.SENTENCE) == fixed


def test_no_rule_no_suggestion():
    assert suggest("anything goes", ItemCase.ANY) is None
