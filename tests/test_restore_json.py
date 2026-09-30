"""Restoring surrogates inside serialized JSON (tool-call arguments).

Two hazards plain text doesn't have: the model may write a surrogate's
non-ASCII delimiters as ``\\uXXXX`` escapes, and an original containing a
quote or backslash must be escaped or the arguments stop being valid JSON.
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from veil.restore import Restorer, restore_json_text
from veil.surrogates import PlaceholderSurrogates
from veil.types import EntityType
from veil.vault import Vault


def _vault() -> Vault:
    vault = Vault()
    gen = PlaceholderSurrogates()
    vault.get_or_create(EntityType.EMAIL, "alice@example.com", gen)
    vault.get_or_create(EntityType.PERSON, 'Anna "Annie" O\\Neil', gen)
    return vault


def test_escaped_and_literal_surrogates_both_restore() -> None:
    args = json.dumps({"to": "⟨EMAIL_1⟩", "cc": "⟨EMAIL_1⟩"}, ensure_ascii=True)
    assert "\\u27e8" in args
    assert json.loads(restore_json_text(args, _vault())) == {
        "to": "alice@example.com",
        "cc": "alice@example.com",
    }
    literal = json.dumps({"to": "⟨EMAIL_1⟩"}, ensure_ascii=False)
    assert json.loads(restore_json_text(literal, _vault())) == {"to": "alice@example.com"}


def test_originals_are_escaped_so_the_json_stays_valid() -> None:
    args = json.dumps({"name": "⟨PERSON_1⟩"}, ensure_ascii=False)
    assert json.loads(restore_json_text(args, _vault())) == {"name": 'Anna "Annie" O\\Neil'}


@given(
    ascii_only=st.booleans(),
    cuts=st.lists(st.integers(min_value=0, max_value=200), max_size=30),
)
@settings(max_examples=200)
def test_streamed_arguments_match_the_whole_string_for_any_chunking(
    ascii_only: bool, cuts: list[int]
) -> None:
    vault = _vault()
    args = json.dumps(
        {"to": "⟨EMAIL_1⟩", "name": "⟨PERSON_1⟩", "note": "ok"}, ensure_ascii=ascii_only
    )
    points = sorted({c % (len(args) + 1) for c in cuts})
    chunks = [args[a:b] for a, b in zip([0, *points], [*points, len(args)], strict=True)]
    restorer = Restorer(vault, json_string=True)
    streamed = "".join(restorer.feed(c) for c in chunks) + restorer.flush()
    assert streamed == restore_json_text(args, vault)
    assert json.loads(streamed) == {
        "to": "alice@example.com",
        "name": 'Anna "Annie" O\\Neil',
        "note": "ok",
    }
