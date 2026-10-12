"""Full URL masking and exact restoration on retained, offline SDK fixtures."""

import json
from pathlib import Path

import pytest

from veil import Masker
from veil.detectors.url import UrlCredentialDetector

CASES = json.loads((Path(__file__).parents[1] / "studies/credential-urls/cases.json").read_text())[
    "cases"
]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_credential_url_boundary_and_restore(case: dict[str, object]) -> None:
    url = str(case["url"])
    text = f'Before "{url}" after.'
    expected = 'Before "⟨URL_CREDENTIAL_1⟩" after.' if case["mask"] else text
    found = UrlCredentialDetector().find(text)
    assert [entity.value for entity in found] == ([url] if case["mask"] else [])
    assert all(text[entity.span.start : entity.span.end] == url for entity in found)
    masker = Masker()
    masked = masker.mask(text)
    assert masked == expected
    assert [m.original for m in masker.vault.mappings()] == ([url] if case["mask"] else [])
    assert masker.restore(masked) == masker.restore(masked, tolerant=False) == text
