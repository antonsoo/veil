"""Flow-scalar credentials use native YAML bounds without exposing suffixes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veil import Masker, Restorer
from veil.detectors.secrets import SecretDetector

NATIVE = json.loads(
    (Path(__file__).parents[1] / "studies/yaml-flow-credentials/fixtures/native.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", NATIVE, ids=[c["id"] for c in NATIVE])
def test_native_values_are_complete_raw_spans(case: dict) -> None:
    masker = Masker()
    masked = masker.mask(case["source"])
    assert masked == case["expected_masked"]
    assert [m.original for m in masker.vault.mappings()] == [case["raw_body"]]
    assert masker.restore(masked, tolerant=False) == case["source"]
    restorer = Restorer(masker.vault)
    assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == case["source"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("quote", ["'", '"'])
def test_blank_lines_bom_and_compact_sequences(quote: str, newline: str) -> None:
    body = newline.join(["river", "", "    stone"])
    source = f"\ufeff- 'client_secret': {quote}{body}{quote} # diagnostic{newline}  mode: read-only"
    masker = Masker()
    assert masker.mask(source) == source.replace(body, "⟨SECRET_1⟩")
    assert masker.restore(masker.mask(source), tolerant=False) == source


def test_quoted_body_owns_block_looking_and_assignment_looking_content() -> None:
    source = 'password: "river\n  api_key: |\n    stone"\nclient_secret: |-\n  quiet\n  meadow\nstatus: failed\n'
    expected = 'password: "⟨SECRET_1⟩"\nclient_secret: |-\n  ⟨SECRET_2⟩\nstatus: failed\n'
    masker = Masker()
    assert masker.mask(source) == expected
    assert [m.original for m in masker.vault.mappings()] == [
        "river\n  api_key: |\n    stone",
        "quiet\n  meadow",
    ]
    assert masker.restore(expected, tolerant=False) == source


@pytest.mark.parametrize("quote", ["'", '"'])
def test_malformed_quote_stops_at_next_mapping_without_hiding_its_credential(quote: str) -> None:
    source = f"connection:\n  password: {quote}unterminated\n    still unterminated\n  api_key: short\nstatus: failed\n"
    masker = Masker()
    assert masker.mask(source) == source.replace("short", "⟨SECRET_1⟩")
    assert masker.restore(masker.mask(source), tolerant=False) == source


@pytest.mark.parametrize(
    "source",
    [
        "password='sun''rise'",
        'password="sun""rise"',
        "prose password: 'sun''rise'",
        "note: 'sun''rise'",
        "password: ''\nstatus: failed",
        'password: ""\nstatus: failed',
    ],
)
def test_empty_noncredential_and_unsupported_concatenations_do_not_mask_a_prefix(
    source: str,
) -> None:
    assert SecretDetector().find(source) == []


def test_yaml_single_quote_backslashes_do_not_escape_the_closing_quote() -> None:
    source = "password: 'river\\'\napi_key: short\n"
    masker = Masker()
    assert masker.mask(source) == "password: '⟨SECRET_1⟩'\napi_key: ⟨SECRET_2⟩\n"
    assert [m.original for m in masker.vault.mappings()] == ["river\\", "short"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("header", ["password: ", "password:\n  "])
def test_plain_values_preserve_comments_and_sibling_fields(header: str, newline: str) -> None:
    body = "river,stone sun'rise\\\n\n    quiet meadow"
    source = (header + body + "  # diagnostic\nmode: read-only\n").replace("\n", newline)
    masker = Masker()
    assert masker.mask(source) == source.replace(body.replace("\n", newline), "⟨SECRET_1⟩")
    assert masker.restore(masker.mask(source), tolerant=False) == source


@pytest.mark.parametrize(
    "source",
    [
        "password:\n  provider: local\nmode: safe\n",
        "password:\n  - river\n  - stone\n",
        "password: &reference river\n",
        "password: *reference\n",
        "password: !tag river\n",
        "password: null # diagnostic\n",
        "password: true\n",
        "password: string;\n",
        "password:\n# diagnostic\nmode: safe\n",
    ],
)
def test_plain_mapping_context_does_not_turn_structures_or_empty_values_into_credentials(
    source: str,
) -> None:
    assert SecretDetector().find(source) == []


def test_plain_comment_ends_the_credential_and_keeps_separate_assignments() -> None:
    source = "password: river stone # api_key=short\nmode: safe\n"
    masker = Masker()
    assert masker.mask(source) == "password: ⟨SECRET_1⟩ # api_key=⟨SECRET_2⟩\nmode: safe\n"
    assert [m.original for m in masker.vault.mappings()] == ["river stone", "short"]


def test_delimited_log_fields_keep_their_existing_boundary() -> None:
    # This spelling is also a legal YAML plain string. Raw text does not
    # establish the format: retain the log-field convention and document this
    # ambiguity instead of claiming comprehensive YAML parsing.
    source = "client_secret: short-secret, status=error\n"
    masker = Masker()
    assert masker.mask(source) == "client_secret: ⟨SECRET_1⟩, status=error\n"


def test_plain_scalar_owns_a_block_looking_colon_without_separating_space() -> None:
    source = "password: river\n  api_key:|-\n    stone\nclient_secret: quiet\nmode: safe\n"
    masker = Masker()
    assert masker.mask(source) == "password: ⟨SECRET_1⟩\nclient_secret: ⟨SECRET_2⟩\nmode: safe\n"
    assert [m.original for m in masker.vault.mappings()] == [
        "river\n  api_key:|-\n    stone",
        "quiet",
    ]
