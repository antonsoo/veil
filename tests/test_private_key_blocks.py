"""Whole opaque keys must survive the complete default detector pipeline."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from veil import Masker, Restorer
from veil.detectors.secrets import SecretDetector
from veil.integrations._common import mask_value, restore_value
from veil.integrations._json_arguments import mask_arguments, restore_arguments

COMMENTS = [
    "synthetic-owner@example.org",
    "10.23.45.67",
    "4111111111111111",
    "GB82 WEST 1234 5698 7654 32",
    "Owner (support) <synthetic-owner@example.org>",
    "操作员 <synthetic-owner@example.org>",
    "Authorization: Bearer abc",
    "password=short-value",
]


def armor(comment: str, *, closed: bool, newline: str = "\n") -> str:
    # An armor-shaped synthetic body, never a real signing/private key.
    label = "PGP " + "PRIVATE KEY BLOCK"
    lines = [
        f"-----BEGIN {label}-----",
        "Version: synthetic",
        f"Comment: {comment}",
        "X-Note: arbitrary UTF-8 text 🔑",
        "",
        "YWFhYQ==",
    ]
    if closed:
        lines.append(f"-----END {label}-----")
    return newline.join(lines)


@pytest.mark.parametrize("comment", COMMENTS)
@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_default_pipeline_keeps_metadata_and_body_in_one_secret(
    comment: str, closed: bool, newline: str
) -> None:
    key = armor(comment, closed=closed, newline=newline)
    masker = Masker()
    assert masker.mask(key) == "⟨SECRET_1⟩"
    assert [m.original for m in masker.vault.mappings()] == [key]
    assert masker.restore("⟨SECRET_1⟩") == masker.restore("⟨SECRET_1⟩", tolerant=False) == key
    restorer = Restorer(masker.vault)
    assert "".join(restorer.feed(c) for c in "⟨SECRET_1⟩") + restorer.flush() == key


def test_truncated_body_does_not_consume_punctuated_following_context() -> None:
    key = armor("synthetic-owner@example.org", closed=False)
    masker = Masker()
    source = key + "\n!Keep this diagnostic context.\n"
    assert masker.mask(source) == "⟨SECRET_1⟩!Keep this diagnostic context.\n"
    assert masker.restore(masker.mask(source)) == source


def test_truncated_header_is_reviewed_as_part_of_the_explicit_key() -> None:
    label = "PGP " + "PRIVATE KEY BLOCK"
    source = f"-----BEGIN {label}-----\nComment: synthetic-owner@example.org"
    assert Masker().mask(source) == "⟨SECRET_1⟩"


@pytest.mark.parametrize(
    "label", ["RSA PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY", "ENCRYPTED PRIVATE KEY"]
)
def test_complete_private_key_labels_own_nested_high_confidence_matches(label: str) -> None:
    source = (
        f"-----BEGIN {label}-----\nsynthetic-owner@example.org\nYWFhYQ==\n-----END {label}-----"
    )
    assert Masker().mask(source) == "⟨SECRET_1⟩"


@pytest.mark.parametrize(
    "label", ["PUBLIC KEY", "PGP PUBLIC KEY BLOCK", "CERTIFICATE", "PGP MESSAGE", "PGP SIGNATURE"]
)
def test_other_armor_labels_do_not_gain_private_key_scope(label: str) -> None:
    source = f"-----BEGIN {label}-----\nComment: synthetic-owner@example.org\nYWFhYQ==\n-----END {label}-----"
    assert Masker().mask(source) == source.replace("synthetic-owner@example.org", "⟨EMAIL_1⟩")


def test_large_unicode_header_and_repeated_blocks() -> None:
    source = armor("🔑" * 100_000 + " synthetic-owner@example.org", closed=False)
    assert [e.value for e in SecretDetector().find(source)] == [source]
    short = armor("synthetic-owner@example.org", closed=True)
    assert [e.value for e in SecretDetector().find((short + "\n") * 1_000)] == [short] * 1_000


def test_decoded_tool_key_is_opaque_and_json_restoration_preserves_escapes() -> None:
    key = armor("synthetic-owner@example.org", closed=True)
    source = {"signing_material": key, "other": "ordinary"}
    masker = Masker()
    assert mask_value(source, masker) == {"signing_material": "⟨SECRET_1⟩", "other": "ordinary"}
    assert restore_value(mask_value(source, masker), masker) == source
    raw = json.dumps(source, ensure_ascii=False)
    other = Masker()
    masked = mask_arguments(raw, other)
    assert json.loads(masked) == {"signing_material": "⟨SECRET_1⟩", "other": "ordinary"}
    assert restore_arguments(masked, other) == raw


@pytest.mark.parametrize("api", ["chat", "responses", "anthropic"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_real_sdk_tool_key_material_is_wholly_masked_and_restored(
    api: str, asynchronous: bool, streaming: bool
) -> None:
    capture = runpy.run_path(
        str(Path(__file__).parents[1] / "studies/http-authorization/sdk_tools.py")
    )["sdk_tool_capture"]
    source = json.dumps(
        {"signing_material": armor("synthetic-owner@example.org", closed=True), "ordinary": "Keep"},
        ensure_ascii=False,
    )
    expected = json.dumps(
        {"signing_material": "⟨SECRET_1⟩", "ordinary": "Keep"}, ensure_ascii=False
    )
    result = capture(
        api, asynchronous, streaming, source=source, expected=expected, tool_reply=True
    )
    assert result["correct"]
    assert result["unrelatedSyntaxPreserved"]
