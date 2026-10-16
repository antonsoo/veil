"""Explicit labels protect short credentials through text and JSON traversal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veil import Masker, Restorer, VaultError
from veil.detectors.email import EmailDetector
from veil.detectors.secrets import SecretDetector
from veil.integrations._common import mask_value, restore_value
from veil.integrations._json_arguments import mask_arguments, restore_arguments

CASES = json.loads(
    (Path(__file__).parents[1] / "studies/credential-fields/cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_credential_assignments_and_controls(case: dict) -> None:
    masker = Masker()
    masked = masker.mask(case["source"])
    assert masked == case["expected"]
    assert masker.restore(masked) == masker.restore(masked, tolerant=False) == case["source"]


@given(st.text(min_size=1))
def test_json_escaped_value_is_one_raw_span(value: str) -> None:
    # json.dumps supplies the independent string spelling, including quotes,
    # control characters and Unicode escapes. No JSON parse/rewrite by masking.
    source = json.dumps({"password": value})
    encoded = json.dumps(value)[1:-1]
    masker = Masker()
    assert masker.mask(source) == '{"password": "⟨SECRET_1⟩"}'
    assert [m.original for m in masker.vault.mappings()] == [encoded]
    assert masker.restore('{"password": "⟨SECRET_1⟩"}') == source


@given(st.text(min_size=1))
def test_decoded_context_keeps_original_bytes_without_invented_escaping(value: str) -> None:
    masker = Masker()
    # A secret field stores the decoded value, even a multiline phrase or a
    # value shaped like another entity. Raw recognition is deliberately bounded.
    assert masker.mask(value, field_name="password") == "⟨SECRET_1⟩"
    assert [m.original for m in masker.vault.mappings()] == [value]
    restorer = Restorer(masker.vault)
    assert "".join(restorer.feed(c) for c in "⟨SECRET_1⟩") + restorer.flush() == value


def test_context_obeys_detector_configuration_and_works_with_legacy_detectors() -> None:
    source = {"password": "river stone", "api_key": "short", "email": "test@example.org"}
    masker = Masker(detectors=[EmailDetector()])
    assert mask_value(source, masker) == {**source, "email": "⟨EMAIL_1⟩"}
    assert Masker(detectors=[]).mask("river stone", field_name="password") == "river stone"
    assert Masker().find_entities("river stone") == []
    assert Masker().find_entities("river stone", field_name="password")[0].type.value == "SECRET"


def test_immediate_string_values_only_and_no_caller_mutation() -> None:
    source = {
        "password": ["river stone"],
        "access_token": {"value": "short"},
        "client_secret": "null",
        "other": "ordinary",
    }
    masker = Masker()
    masked = mask_value(source, masker)
    assert masked == {**source, "client_secret": "⟨SECRET_1⟩"}
    assert source["client_secret"] == "null"
    assert restore_value(masked, masker) == source
    raw = json.dumps(source)
    other = Masker()
    assert json.loads(mask_arguments(raw, other)) == masked
    assert restore_arguments(mask_arguments(raw, other), other) == raw


def test_literal_reservations_repeated_values_and_transaction_rollback() -> None:
    source = '{"password":"river stone", "password":"river stone", "literal":"⟨SECRET_1⟩"}'
    masker = Masker()
    expected = source.replace("river stone", "⟨SECRET_2⟩")
    assert mask_arguments(source, masker) == expected
    assert len(masker.vault) == 1
    assert restore_arguments(expected, masker) == source
    before = masker.vault.to_json()
    with pytest.raises(VaultError, match="surrogate"):
        mask_arguments('{"password":"new", "literal":"⟨SECRET_2⟩"}', masker)
    assert masker.vault.to_json() == before


@pytest.mark.parametrize(
    "source",
    [
        '"password\':"river stone"',
        "PASSWORD=$LOCAL_PASSWORD",
        "password=river\\ stone",
        "password='river'+'stone'",
        "password=get_password()",
        "password:\nnext line",
        "https://example.org/access_token=path-label",
        "https://example.org/?api_key=short",
        "file.password=plain",
        "get_password=plain",
        "database_password=plain",
    ],
)
def test_rule_does_not_mask_partial_expressions_or_url_components(source: str) -> None:
    assert not any(e.detector == "secret:credential_field" for e in SecretDetector().find(source))


def test_long_quoted_values_and_malformed_pastes() -> None:
    value = 'a\\"' * 50_000
    source = f'password="{value}"\npassword="unterminated\napi_key=short'
    found = SecretDetector().find(source)
    assert [e.value for e in found] == [value, "short"]


def test_context_cannot_expose_an_enclosing_private_key_block() -> None:
    dashes = "-" * 5
    label = "PRIVATE " + "KEY"
    key = f"{dashes}BEGIN {label}{dashes}\nComment: password=abc\nYWFhYQ==\n{dashes}END {label}{dashes}"
    found = SecretDetector().find(key)
    assert [(e.value, e.detector) for e in found] == [(key, "secret:private_key")]
    # Conversely, a quoted enclosing credential must not be fragmented at a
    # key-shaped substring in its single-line value.
    value = key.replace("\n", " ")
    found = SecretDetector().find(f'password="prefix {value} suffix"')
    assert [(e.value, e.detector) for e in found] == [
        (f"prefix {value} suffix", "secret:credential_field")
    ]
