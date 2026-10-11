"""Tool history is JSON data, not the spelling of its encoded strings."""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veil import Masker, VaultError
from veil.backends import KnownEntitiesBackend
from veil.integrations._json_arguments import mask_arguments
from veil.restore import restore_json_text


@pytest.mark.parametrize(
    "raw",
    [
        r'{"to":"alice\u0040example.org"}',
        r'{"to":"\u0061\u006c\u0069\u0063\u0065\u0040\u0065\u0078\u0061\u006d\u0070\u006c\u0065\u002e\u006f\u0072\u0067"}',
        r'{"nested":[{"name":"Zo\u00eb Example"},"alice\u0040example.org"]}',
        r'["alice\u0040example.org",null,false,123]',
        r'"alice\u0040example.org"',
    ],
)
def test_decoded_values_are_masked_and_restore_to_their_original_data(raw: str) -> None:
    masker = Masker(name_backends=[KnownEntitiesBackend(persons=["Zoë Example"])])
    masked = mask_arguments(raw, masker)
    decoded = json.dumps(json.loads(masked), ensure_ascii=False)
    assert "alice@example.org" not in decoded
    assert "Zoë Example" not in decoded
    assert len(masker.vault) > 0
    assert json.loads(restore_json_text(masked, masker.vault)) == json.loads(raw)


def test_only_changed_tokens_are_rewritten_including_duplicate_members() -> None:
    raw = (
        ' { "n":1.234567890123456789e+40, "n":-0, "flag":false,\n'
        r'"untouched":"\u0061 \/ \\u0040", "to":"alice\u0040example.org",'
        r'"to":"bob\u0040example.org", "huge":' + "1" * 5000 + " }\n"
    )
    masked = mask_arguments(raw, Masker())
    assert masked == raw.replace(r"alice\u0040example.org", "⟨EMAIL_1⟩").replace(
        r"bob\u0040example.org", "⟨EMAIL_2⟩"
    )


def test_literal_backslashes_are_not_decoded_twice() -> None:
    raw = r'{"example":"alice\\u0040example.org","emoji":"\ud83d\ude00"}'
    masker = Masker()
    assert mask_arguments(raw, masker) == raw
    assert len(masker.vault) == 0


def test_escaped_literal_placeholder_reserves_its_decoded_identity() -> None:
    raw = r'{"to":"alice\u0040example.org","example":"\u27E8EMAIL_1\u27E9"}'
    masker = Masker()
    masked = mask_arguments(raw, masker)
    assert json.loads(masked) == {"to": "⟨EMAIL_2⟩", "example": "⟨EMAIL_1⟩"}
    assert json.loads(restore_json_text(masked, masker.vault)) == json.loads(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        '{"to":"alice\\u0040example.org"',
        '{"to":"alice@example.org",}',
        '{"to":"alice@example.org","n":NaN}',
        '{"n":Infinity}',
        '{"n":-Infinity}',
        '"bad\\x40escape"',
        '"unescaped\nnewline"',
        "{} {}",
    ],
)
def test_invalid_arguments_fail_without_allocating_or_echoing_sensitive_data(raw: str) -> None:
    masker = Masker()
    before = masker.vault.to_json()
    with pytest.raises(VaultError, match="complete, valid JSON") as caught:
        mask_arguments(raw, masker)
    assert "alice" not in str(caught.value)
    assert masker.vault.to_json() == before


def test_sensitive_object_keys_are_rejected_instead_of_renamed_or_leaked() -> None:
    masker = Masker()
    with pytest.raises(VaultError, match="sensitive JSON key"):
        mask_arguments(r'{"alice\u0040example.org":"yes"}', masker)
    assert len(masker.vault) == 0


@given(escaped=st.lists(st.booleans(), min_size=1, max_size=100))
@settings(max_examples=150)
def test_arbitrary_json_escape_spelling_cannot_hide_a_known_value(escaped: list[bool]) -> None:
    source = 'Contact Zoë Example: alice@example.org; "quoted" \\ path\n😀'
    parts = []
    for index, char in enumerate(source):
        if escaped[index % len(escaped)]:
            units = char.encode("utf-16-be")
            parts.append("".join("\\u" + units[i : i + 2].hex() for i in range(0, len(units), 2)))
        else:
            parts.append(json.dumps(char, ensure_ascii=False)[1:-1])
    raw = '{"nested":["' + "".join(parts) + '",123,null]}'
    masker = Masker(name_backends=[KnownEntitiesBackend(persons=["Zoë Example"])])
    masked = mask_arguments(raw, masker)
    assert json.loads(masked) == {
        "nested": ['Contact ⟨PERSON_1⟩: ⟨EMAIL_1⟩; "quoted" \\ path\n😀', 123, None]
    }
    assert json.loads(restore_json_text(masked, masker.vault)) == json.loads(raw)
