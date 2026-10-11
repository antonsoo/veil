"""Complete tool replies must preserve the data the application will execute."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from veil import Masker, Vault
from veil.integrations._common import restore_arguments
from veil.restore import Restorer


@pytest.mark.parametrize(
    "number",
    ["0.12345678901234567890", "1e309", "-0.00E-03", "9007199254740993", "1" * 5000],
    ids=["precise-decimal", "large-exponent", "negative-zero", "large-integer", "long-integer"],
)
def test_complete_and_streamed_replies_preserve_numeric_tokens(number: str) -> None:
    masker = Masker()
    token = masker.mask("alice@example.org")
    raw = '{ "to":"' + token + '", "n":' + number + ', "n":2, "literal":"\\u0061" }'
    expected = raw.replace(token, "alice@example.org")
    restored = restore_arguments(raw, masker)
    assert restored == expected
    # Decimal is an independent data oracle without binary-float rounding or overflow.
    assert json.loads(restored, parse_float=Decimal, parse_int=Decimal, object_pairs_hook=list) == [
        ("to", "alice@example.org"),
        ("n", Decimal(number)),
        ("n", Decimal(2)),
        ("literal", "a"),
    ]
    stream = Restorer(masker.vault, json_string=True)
    assert "".join(stream.feed(char) for char in raw) + stream.flush() == restored


def test_complete_restoration_keeps_tolerant_matching_and_ignores_keys() -> None:
    masker = Masker()
    masker.mask("alice@example.org")
    raw = r'{"\u27E8EMAIL_1\u27E9":["\u27e8email_1\u27e9",1.00e+2]}'
    assert (
        restore_arguments(raw, masker) == r'{"\u27E8EMAIL_1\u27E9":["alice@example.org",1.00e+2]}'
    )


def test_complete_restoration_escapes_originals_without_touching_other_tokens() -> None:
    original = 'Zoë "Example"\nC:\\private\\'
    masker = Masker(
        vault=Vault.from_dict(
            {"mappings": [{"type": "PERSON", "original": original, "surrogate": "⟨PERSON_1⟩"}]}
        )
    )
    raw = ' { "name":"⟨PERSON_1⟩", "n":-0.0001E+9, "literal":"\\u0061" } '
    expected = raw.replace('"⟨PERSON_1⟩"', json.dumps(original, ensure_ascii=False))
    assert restore_arguments(raw, masker) == expected
    assert json.loads(expected)["name"] == original


@pytest.mark.parametrize("ending", [',"n":', ',"n":NaN}', ',"n":Infinity}', ',"unfinished":"'])
def test_malformed_provider_output_is_not_repaired_or_coerced(ending: str) -> None:
    masker = Masker()
    token = masker.mask("alice@example.org")
    raw = '{"to":"' + token + '"' + ending
    assert restore_arguments(raw, masker) == raw.replace(token, "alice@example.org")
