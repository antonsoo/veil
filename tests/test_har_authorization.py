from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from veil import Masker, Restorer, VaultError
from veil._json_fields import json_string_tokens, string_source_span
from veil.integrations._common import mask_value
from veil.integrations._json_arguments import mask_arguments, restore_arguments

DIRECTORY = Path(__file__).parents[1] / "studies/har-authorization/fixtures"
ORACLE = json.loads((DIRECTORY / "oracle.json").read_text())


def har(headers: object) -> dict[str, object]:
    return {"log": {"version": "1.2", "entries": [{"request": {"headers": headers}}]}}


@pytest.mark.parametrize("record", ORACLE["rows"], ids=lambda row: row["engine"])
def test_native_authenticated_requests_keep_schemes_and_restore_source(record: dict) -> None:
    source = (DIRECTORY / record["file"]).read_text()
    for transform in [lambda text, masker: masker.mask(text), mask_arguments]:
        masker = Masker()
        masked = transform(source, masker)
        for credential in ORACLE["credentials"].values():
            assert credential not in masked
        assert '"Authorization"' in masked or '"authorization"' in masked
        assert '"Bearer ⟨SECRET_1⟩"' in masked
        assert '"Basic ⟨SECRET_2⟩"' in masked
        assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
        restorer = Restorer(masker.vault)
        assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source
        assert restore_arguments(masked, masker) == source
    value = json.loads(source)
    original = copy.deepcopy(value)
    masker = Masker()
    masked_value = mask_value(value, masker)
    assert value == original
    assert json.loads(restore_arguments(json.dumps(masked_value), masker)) == original
    assert all(secret not in json.dumps(masked_value) for secret in ORACLE["credentials"].values())


@pytest.mark.parametrize("name", ["Authorization", "authorization", "Proxy-Authorization"])
@pytest.mark.parametrize("side", ["request", "response"])
def test_context_is_local_to_named_header_value(name: str, side: str) -> None:
    value = har(
        [
            {"name": name, "value": "Bearer abc", "comment": "Bearer public"},
            {"name": "X-Public", "value": "Bearer xyz"},
        ]
    )
    entry = value["log"]["entries"][0]
    if side == "response":
        entry[side] = entry.pop("request")
    expected = copy.deepcopy(value)
    expected["log"]["entries"][0][side]["headers"][0]["value"] = "Bearer ⟨SECRET_1⟩"
    for transform in [lambda text, masker: masker.mask(text), mask_arguments]:
        assert json.loads(transform(json.dumps(value), Masker())) == expected
    assert mask_value(value, Masker()) == expected


def test_escaped_header_name_scheme_and_credential_preserve_original_spelling() -> None:
    source = r'{"n":9007199254740993123456789,"n":1.2300e+400,"har":{"lo\u0067":{"version":"1.2","entries":[{"request":{"headers":[{"na\u006de":"Authoriz\u0061tion","value":"\u0042earer\t\u0061b\/c=="}]}}]}}}'
    masker = Masker()
    masked = masker.mask(source)
    assert masked == source.replace(r"\u0061b\/c==", "⟨SECRET_1⟩")
    assert masker.restore(masked) == source
    decoded = Masker()
    masked = mask_arguments(source, decoded)
    assert masked == source.replace(r"\u0042earer\t\u0061b\/c==", r"Bearer\t⟨SECRET_1⟩")
    assert json.loads(restore_arguments(masked, decoded)) == json.loads(source)


@pytest.mark.parametrize(
    "value",
    [
        {"headers": [{"name": "Authorization", "value": "Bearer abc"}]},
        {"name": "Authorization", "value": "Bearer abc"},
        {
            "log": {
                "version": "other",
                "entries": [
                    {"request": {"headers": [{"name": "Authorization", "value": "Bearer abc"}]}}
                ],
            }
        },
        har([{"name": "Authorization", "value": "Digest public"}]),
        har([{"name": "X-Authorization", "value": "Bearer abc"}]),
    ],
)
def test_no_auth_context_is_guessed_outside_supported_shapes(value: dict) -> None:
    source = json.dumps(value)
    assert Masker().mask(source) == source
    assert mask_arguments(source, Masker()) == source
    assert mask_value(value, Masker()) == value


@pytest.mark.parametrize(
    "headers",
    [
        '[{"name":"Authorization","name":"X-Public","value":"Bearer abc"}]',
        '[{"name":"Authorization","value":"Bearer abc","value":"Bearer xyz"}]',
    ],
)
def test_conflicting_auth_routing_rejects_and_rolls_back(headers: str) -> None:
    source = json.dumps(har([])).replace('"headers": []', '"headers": ' + headers)
    for transform in [lambda text, masker: masker.mask(text), mask_arguments]:
        masker = Masker()
        before = masker.vault.to_json()
        with pytest.raises(VaultError, match="HAR"):
            transform(source, masker)
        assert masker.vault.to_json() == before


def test_decoded_span_boundaries_recover_exact_original_json_substrings() -> None:
    source = r'"a\t\u0062\/\ud83d\ude00é\\\"\ud800z"'
    token = json_string_tokens(source)[0]
    for start in range(len(token.value)):
        for end in range(start + 1, len(token.value) + 1):
            a, b = string_source_span(source, token, start, end)
            assert json.loads('"' + source[a:b] + '"') == token.value[start:end]
