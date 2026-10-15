"""Explicit auth headers must not depend on token length, entropy or word shape."""

from __future__ import annotations

import base64
import json

import pytest

from veil import Masker, Restorer
from veil.detectors.secrets import SecretDetector
from veil.integrations._common import mask_value, restore_value
from veil.integrations._json_arguments import mask_arguments, restore_arguments
from veil.vault import VaultError


@pytest.mark.parametrize(
    "credential",
    [
        "abc",
        "aabbccddeeff0011",
        "ab.c_d-ef~g+/==",
        "dXNlcjpwYXNz",
        "Og==",
        "w7xzZXI6cMOkc3N3w7ZyZA==",
        base64.b64encode(b"customer-17:correct horse battery staple").decode(),
    ],
)
@pytest.mark.parametrize("scheme", ["Basic", "Bearer"])
def test_complete_credential_independent_of_entropy(credential: str, scheme: str) -> None:
    source = f"Authorization: {scheme} {credential}\r\n"
    masker = Masker()
    masked = masker.mask(source)
    assert masked == f"Authorization: {scheme} \u27e8SECRET_1\u27e9\r\n"
    assert [m.original for m in masker.vault.mappings()] == [credential]
    assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
    restorer = Restorer(masker.vault)
    assert "".join(restorer.feed(char) for char in masked) + restorer.flush() == source


@pytest.mark.parametrize(
    "source",
    [
        "Authorization: Bearer abc",
        "proxy-authorization: Basic abc",
        "aUtHoRiZaTiOn:\t bEaReR\tabc",
        '{"Authorization": "Bearer abc"}',
        "{'Proxy-Authorization' : 'Basic abc'}",
        "curl -H 'Authorization: Bearer abc' https://example.org",
        'headers["Authorization"] = "Bearer abc"; Authorization: Bearer abc',
        "Header: Authorization: Bearer abc; other metadata",
        "(Authorization: Bearer abc)",
    ],
)
def test_header_log_spellings(source: str) -> None:
    found = [e for e in SecretDetector().find(source) if e.detector == "secret:http_authorization"]
    assert len(found) == 1
    assert found[0].value == "abc"
    assert source[found[0].span.start : found[0].span.end] == "abc"


@pytest.mark.parametrize(
    "source",
    [
        "Basic algebra is useful; Bearer of good news.",
        "Bearer abc",
        "Authorization: Digest username=abc",
        'WWW-Authenticate: Basic realm="abc"',
        "X-Authorization: Bearer abc",
        "NoAuthorization: Bearer abc",
        "\u00e9Authorization: Bearer abc",
        "Authorization: Bearer\r\nabc",
        "Authorization: Basic \nContent-Type: text/plain",
        "Authorization: Basic",
        "Authorization: Bearer ",
        "Authorization: Basic $TOKEN",
        "Authorization: Basic <credentials>",
        # Never recognize a shorter token prefix of a glued unsupported value.
        "Authorization: Bearer abc=def",
        "Authorization: Bearer abc:def",
        "Authorization: Bearer abc%def",
        "Authorization: Bearer abc\u00e9def",
    ],
)
def test_unrelated_or_unsupported_text_is_not_a_contextual_match(source: str) -> None:
    assert not any(e.detector == "secret:http_authorization" for e in SecretDetector().find(source))


def test_explicit_credential_owns_nested_detections_and_reuses_surrogate() -> None:
    # The suffix is Luhn-valid. It must not displace the enclosing auth value.
    credential = "prefix.4111111111111111"
    source = f"Authorization: Bearer {credential}\nProxy-Authorization: Bearer {credential}"
    masker = Masker()
    assert (
        masker.mask(source)
        == "Authorization: Bearer \u27e8SECRET_1\u27e9\nProxy-Authorization: Bearer \u27e8SECRET_1\u27e9"
    )
    assert [m.original for m in masker.vault.mappings()] == [credential]


def test_literal_surrogate_reservation_and_request_rollback() -> None:
    masker = Masker()
    source = "Authorization: Basic dXNlcjpwYXNz; literal \u27e8SECRET_1\u27e9"
    assert (
        masker.mask(source)
        == "Authorization: Basic \u27e8SECRET_2\u27e9; literal \u27e8SECRET_1\u27e9"
    )
    original = masker.vault.to_json()
    with pytest.raises(VaultError, match="conflicts"):
        masker.mask_many(["Authorization: Basic dXNlcjpwYXNz", "literal \u27e8SECRET_2\u27e9"])
    assert masker.vault.to_json() == original


def test_many_headers_and_large_opaque_credentials() -> None:
    # No payload decode, entropy scoring or per-character backward rescans.
    credential = "a" * 250_000 + "/+=="
    source = f"Authorization: Basic {credential}\n" * 3
    found = SecretDetector().find(source)
    assert [e.value for e in found] == [credential] * 3
    assert all(e.detector == "secret:http_authorization" for e in found)


def test_structured_header_values_keep_their_key_context() -> None:
    value = {
        "headers": {"Authorization": "Basic dXNlcjpwYXNz", "Proxy-Authorization": "Bearer abc"}
    }
    masker = Masker()
    masked = mask_value(value, masker)
    assert masked == {
        "headers": {
            "Authorization": "Basic \u27e8SECRET_1\u27e9",
            "Proxy-Authorization": "Bearer \u27e8SECRET_2\u27e9",
        }
    }
    assert restore_value(masked, masker) == value
    assert value["headers"]["Authorization"] == "Basic dXNlcjpwYXNz"


def test_json_string_header_values_preserve_raw_argument_syntax() -> None:
    source = r'{ "headers": {"Authoriz\u0061tion": "Basic dXNlcjpwYXNz", "Proxy-Authorization": "Bearer abc"}, "count":9007199254740993, "count":1.2300e+40 }'
    expected = source.replace("dXNlcjpwYXNz", "\u27e8SECRET_1\u27e9").replace(
        "abc", "\u27e8SECRET_2\u27e9"
    )
    masker = Masker()
    assert mask_arguments(source, masker) == expected
    assert restore_arguments(expected, masker) == source


@pytest.mark.parametrize(
    "value",
    [
        {"Authorization": ["Bearer abc"]},
        {"Authorization": {"value": "Bearer abc"}},
        {"X-Authorization": "Bearer abc"},
        {"other": "Bearer abc"},
    ],
)
def test_header_context_applies_only_to_its_direct_string_value(value: dict) -> None:
    assert mask_value(value, Masker()) == value
    raw = json.dumps(value)
    assert mask_arguments(raw, Masker()) == raw


def test_header_values_share_reservations_with_all_other_argument_values() -> None:
    raw = '{"Authorization":"Bearer abc", "literal":"\u27e8SECRET_1\u27e9"}'
    masker = Masker()
    masked = mask_arguments(raw, masker)
    assert json.loads(masked) == {
        "Authorization": "Bearer \u27e8SECRET_2\u27e9",
        "literal": "\u27e8SECRET_1\u27e9",
    }
    assert restore_arguments(masked, masker) == raw
