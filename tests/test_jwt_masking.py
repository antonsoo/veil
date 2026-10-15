"""Native signed JWTs retain no encoded identity claims in outgoing text."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import jwt
import pytest

from veil import Masker, Restorer
from veil.detectors._jwt import MAX_JWT_HEADER_CHARS, compact_jwt_spans
from veil.detectors.secrets import SecretDetector

FIXTURES = json.loads((Path(__file__).parents[1] / "studies/jwt-claims/cases.json").read_text())[
    "cases"
]


def encoded(value: object) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )


@pytest.mark.parametrize("case", FIXTURES, ids=lambda case: case["id"])
def test_native_jwt_masks_as_one_value_and_matches_independent_signature_oracle(case: dict) -> None:
    token = case["token"]
    assert (
        jwt.decode(
            token,
            case["verificationKey"],
            algorithms=[case["algorithm"]],
            options={
                "verify_exp": False,
                "verify_signature": case["algorithm"] != "none",
            },
        )
        == case["claims"]
    )
    source = f"Authorization: Bearer {token}\r\n"
    masker = Masker()
    masked = masker.mask(source)
    assert masked == "Authorization: Bearer ⟨SECRET_1⟩\r\n"
    assert [m.original for m in masker.vault.mappings()] == [token]
    assert token.split(".")[1] not in masked
    assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
    restorer = Restorer(masker.vault)
    assert "".join(restorer.feed(char) for char in masked) + restorer.flush() == source


@pytest.mark.parametrize("trailing", ["", ".", "...", ",", ";", ")", "'", '"', "\n"])
def test_sentence_punctuation_and_unsigned_final_dot_remain_distinct(trailing: str) -> None:
    for case in [FIXTURES[0], next(c for c in FIXTURES if c["id"] == "unsecured")]:
        token = case["token"]
        masker = Masker()
        source = f"token={token}{trailing}"
        assert masker.mask(source) == f"token=⟨SECRET_1⟩{trailing}"
        assert masker.restore(f"token=⟨SECRET_1⟩{trailing}") == source


def test_token_and_header_do_not_require_verified_authentication() -> None:
    header, payload, _ = FIXTURES[0]["token"].split(".")
    # Altered signatures still expose the claims; a privacy detector must mask
    # them even though an authentication verifier correctly refuses the token.
    damaged = f"{header}.{payload}.not-a-valid-signature"
    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(damaged, FIXTURES[0]["verificationKey"], algorithms=["HS256"])
    assert Masker().mask(damaged) == "⟨SECRET_1⟩"
    unknown = f"{encoded({'alg': 'private/custom'})}.{payload}.opaque-signature"
    assert Masker().mask(unknown) == "⟨SECRET_1⟩"


def test_complete_token_wins_over_card_shaped_signature_but_url_can_enclose_it() -> None:
    head, payload, _ = FIXTURES[0]["token"].split(".")
    token = f"{head}.{payload}.4111111111111111"
    assert Masker().mask(token) == "⟨SECRET_1⟩"
    url = f"https://example.org/callback?access_token={token}"
    assert Masker().mask(url) == "⟨URL_CREDENTIAL_1⟩"


def test_repeated_token_reuses_one_mapping_and_preserves_json_fields() -> None:
    token = FIXTURES[0]["token"]
    source = json.dumps({"access_token": token, "history": [token]})
    masker = Masker()
    masked = masker.mask(source)
    assert json.loads(masked) == {"access_token": "⟨SECRET_1⟩", "history": ["⟨SECRET_1⟩"]}
    assert len(masker.vault) == 1 and masker.restore(masked) == source


@pytest.mark.parametrize(
    "header",
    [
        None,
        [],
        {},
        {"alg": None},
        {"alg": True},
        {"alg": ""},
        {"alg": " "},
        {"alg": "RSA-OAEP", "enc": "A256GCM"},
    ],
)
def test_non_jwt_headers_do_not_create_new_known_credentials(header: object) -> None:
    assert list(compact_jwt_spans(f"{encoded(header)}.e30.signature")) == []


def test_multipart_and_invalid_headers_never_become_shorter_jwt_matches() -> None:
    token = FIXTURES[0]["token"]
    for source in [
        "prefix" + token,
        token + ".another",
        token + ".another.part",
        token + "=bad",
        token + "界",
        "界" + token,
    ]:
        assert list(compact_jwt_spans(source)) == []
    for header in [
        "not-json",
        "_",
        encoded("a string"),
        base64.urlsafe_b64encode(b"\xff").decode().rstrip("="),
    ]:
        assert list(compact_jwt_spans(f"{header}.e30.signature")) == []
    signed_head, payload, _ = token.split(".")
    assert list(compact_jwt_spans(f"{signed_head}.{payload}.")) == []


def test_bounded_header_inspection_does_not_bound_the_opaque_claims() -> None:
    header = encoded({"alg": "HS256", "kid": "x" * MAX_JWT_HEADER_CHARS})
    assert len(header) > MAX_JWT_HEADER_CHARS
    assert list(compact_jwt_spans(f"{header}.e30.signature")) == []
    long = f"{encoded({'alg': 'HS256'})}.{'a' * 200_000}.signature"
    assert [e.value for e in SecretDetector().find(long)] == [long]


def test_padded_compatibility_spelling_preserves_the_exact_signed_bytes() -> None:
    header = base64.urlsafe_b64encode(b'{"alg": "HS256"}').decode()
    payload = base64.urlsafe_b64encode(b'{"email": "alice@example.org"}').decode()
    key = FIXTURES[0]["verificationKey"]
    signature = base64.urlsafe_b64encode(
        hmac.new(key.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    ).decode()
    token = f"{header}.{payload}.{signature}"
    assert "=" in token
    assert jwt.decode(token, key, algorithms=["HS256"]) == {"email": "alice@example.org"}
    masker = Masker()
    assert masker.mask(token) == "⟨SECRET_1⟩"
    assert masker.restore("⟨SECRET_1⟩") == token


def test_deep_oversized_header_is_rejected_before_json_parsing() -> None:
    raw = b'{"alg":"HS256","extra":' + b"[" * 10_000 + b"0" + b"]" * 10_000 + b"}"
    header = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert len(header) > MAX_JWT_HEADER_CHARS
    assert list(compact_jwt_spans(f"{header}.e30.signature")) == []
