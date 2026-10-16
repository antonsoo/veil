"""Credential contents must not escape behind a YAML syntax placeholder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veil import Masker, Restorer
from veil.detectors.secrets import SecretDetector

NATIVE = json.loads(
    (Path(__file__).parents[1] / "studies/yaml-credentials/fixtures/native.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", NATIVE, ids=[c["id"] for c in NATIVE])
def test_native_writer_values_are_opaque_with_neighboring_configuration_retained(
    case: dict,
) -> None:
    source = case["source"]
    masker = Masker()
    masked = masker.mask(source)
    assert len(masker.vault) == 1
    assert all(value not in masked for value in case["sensitive_fragments"])
    assert all(value in masked for value in case["retained_fragments"])
    assert case["header"] + "\n" in masked
    found = masker.find_entities(source)
    assert len(found) == 1 and found[0].detector == "secret:credential_field"
    start, end = case["native_scalar_span"]
    assert start < found[0].span.start < found[0].span.end <= end
    assert masker.restore(masked, tolerant=False) == source
    restorer = Restorer(masker.vault)
    assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source


@pytest.mark.parametrize("style", ["|", ">"])
@pytest.mark.parametrize("indicators", ["", "-", "+", "2", "2-", "-2", "2+", "+2"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_indentation_chomping_sequence_and_line_break_boundaries(
    style: str,
    indicators: str,
    newline: str,
) -> None:
    source = newline.join(
        [
            f'- "client_secret": {style}{indicators} # diagnostic header',
            "    river",
            "    api_key=stone",
            "  # boundary comment",
            "  mode: read-only",
            "  note: |",
            "    ordinary text",
            "",
        ]
    )
    expected = newline.join(
        [
            f'- "client_secret": {style}{indicators} # diagnostic header',
            "    ⟨SECRET_1⟩",
            "  # boundary comment",
            "  mode: read-only",
            "  note: |",
            "    ordinary text",
            "",
        ]
    )
    masker = Masker()
    assert masker.mask(source) == expected
    assert masker.restore(expected, tolerant=False) == source


def test_multiple_blocks_and_plain_values_keep_source_order_and_reservations() -> None:
    source = "password=first\npassword: |-\n  river\n  stone\napi_key=second\nclient_secret: >\n  last\nliteral: ⟨SECRET_1⟩\n"
    masked = "password=⟨SECRET_2⟩\npassword: |-\n  ⟨SECRET_3⟩\napi_key=⟨SECRET_4⟩\nclient_secret: >\n  ⟨SECRET_5⟩\nliteral: ⟨SECRET_1⟩\n"
    masker = Masker()
    assert masker.mask(source) == masked
    assert masker.restore(masked, tolerant=False) == source


@pytest.mark.parametrize(
    "source",
    [
        "password: |\nstatus: failed\n",
        "password: >-\n\nstatus: failed\n",
        "# password: |\n  river\n  stone\n",
        "note: |\n  river\n  stone\n",
        "password: |0\n  river\n",
        "password=|\n  river\n",
        "prose password: |\n  river\n",
        "password: |\n\triver\n",
    ],
)
def test_empty_unsupported_and_noncredential_blocks_do_not_mask_syntax(source: str) -> None:
    assert SecretDetector().find(source) == []


def test_bom_explicit_extra_indentation_and_no_final_newline() -> None:
    source = "\ufeffpassword: |2-\n     river\n   stone"
    masker = Masker()
    assert masker.mask(source) == "\ufeffpassword: |2-\n  ⟨SECRET_1⟩"
    assert masker.restore("\ufeffpassword: |2-\n  ⟨SECRET_1⟩", tolerant=False) == source
