"""Compare streamed restoration with an independently parsed JSON value tree."""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veil.restore import Restorer, restore_json_text
from veil.vault import Vault

_PAIRS = {
    "⟨EMAIL_1⟩": "alice@example.com",
    'A"B\\C': 'Original "person"\nwith a slash \\',
    "😀/☃": "Private snowman",
    "12": "private number",
    "abc": "short original",
    "abcdef": "long original",
}
_VAULT = Vault.from_dict(
    {
        "mappings": [
            {"type": "PERSON", "surrogate": surrogate, "original": original}
            for surrogate, original in _PAIRS.items()
        ]
    }
)


def _reference(value: Any) -> Any:
    if isinstance(value, list):
        return [_reference(item) for item in value]
    if isinstance(value, dict):
        return {key: _reference(item) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    out: list[str] = []
    pos = 0
    while pos < len(value):
        match = next(
            (s for s in sorted(_PAIRS, key=len, reverse=True) if value.startswith(s, pos)), None
        )
        if match is None:
            out.append(value[pos])
            pos += 1
        else:
            out.append(_PAIRS[match])
            pos += len(match)
    return "".join(out)


@pytest.mark.parametrize(
    "raw",
    [
        '{"to":"\\u27E8EMAIL_1\\u27E9"}',
        '{"to":"⟨EMAIL_\\u0031⟩"}',
        '{"literal":"\\\\u27e8EMAIL_1\\u27e9"}',
        '{"literal":"\\\\u27e8EMAIL_1\\\\u27e9"}',
        '{"v":"\\ud83d\\ude00\\/\\u2603"}',
        '{"v":"A\\"B\\\\C"}',
        '{"12":12,"abc":["12",null,false,{"abcdef":"abcdefabc"}]}',
        ' [ "abc", 12, "abcdef" ] ',
        '"⟨EMAIL_1⟩"',
    ],
)
def test_json_syntax_is_decoded_before_matching_at_every_split(raw: str) -> None:
    expected = _reference(json.loads(raw))
    for cut in range(len(raw) + 1):
        restorer = Restorer(_VAULT, json_string=True)
        result = restorer.feed(raw[:cut]) + restorer.feed(raw[cut:]) + restorer.flush()
        assert json.loads(result) == expected


def test_untouched_spelling_is_preserved_exactly() -> None:
    raw = ' { "abc" : "\\\\u27e8EMAIL_1\\u27E9", "n":1.20e+03, "other":"\\u0061b \\/" }\n'
    restorer = Restorer(_VAULT, json_string=True)
    assert "".join(restorer.feed(char) for char in raw) + restorer.flush() == raw


@given(
    tokens=st.lists(
        st.sampled_from([*_PAIRS, '"', "\\", "\n", "é", "☃", "nothing", r"\u27e8EMAIL_1⟩"]),
        max_size=20,
    ),
    escaped=st.lists(st.booleans(), min_size=1, max_size=80),
    uppercase=st.booleans(),
    cuts=st.lists(st.integers(min_value=0, max_value=500), max_size=40),
)
@settings(max_examples=250)
def test_mixed_escapes_match_an_independent_value_oracle(
    tokens: list[str], escaped: list[bool], uppercase: bool, cuts: list[int]
) -> None:
    value = " | ".join(tokens)
    encoded: list[str] = []
    for index, char in enumerate(value):
        if escaped[index % len(escaped)]:
            units = char.encode("utf-16-be")
            encoded.append(
                "".join(
                    "\\u"
                    + (units[i : i + 2].hex().upper() if uppercase else units[i : i + 2].hex())
                    for i in range(0, len(units), 2)
                )
            )
        else:
            encoded.append(json.dumps(char, ensure_ascii=False)[1:-1])
    raw = '{"abc": [12, {"12": "' + "".join(encoded) + '"}]}'
    boundaries = sorted({0, len(raw), *(cut % (len(raw) + 1) for cut in cuts)})
    restorer = Restorer(_VAULT, json_string=True)
    output = (
        "".join(
            restorer.feed(raw[start:end])
            for start, end in zip(boundaries, boundaries[1:], strict=False)
        )
        + restorer.flush()
    )
    assert json.loads(output) == _reference(json.loads(raw))
    assert output == restore_json_text(raw, _VAULT)


def test_unfinished_json_is_flushed_without_inventing_syntax() -> None:
    for raw in ['{"v":"ab', '{"v":"\\u27', '{"v":"\\', '{"v":"\\uXXXX']:
        restorer = Restorer(_VAULT, json_string=True)
        assert "".join(restorer.feed(char) for char in raw) + restorer.flush() == raw


def test_a_large_string_emits_incrementally_instead_of_waiting_for_its_end() -> None:
    restorer = Restorer(_VAULT, json_string=True)
    assert restorer.feed('{"v":"') == '{"v":"'
    for _ in range(1000):
        assert restorer.feed("plain words " * 100) == "plain words " * 100
    assert restorer.feed('"}') + restorer.flush() == '"}'
