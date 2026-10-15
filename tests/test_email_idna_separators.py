"""Protect whole IDNA domain spellings without changing stored identities."""

from __future__ import annotations

import itertools

import pytest

from veil import Masker, Restorer
from veil.detectors.email import EmailDetector

SEPARATORS = ".\u3002\uff0e\uff61"


def test_every_mixed_idna_separator_sequence_against_independent_codec() -> None:
    for a, b, c in itertools.product(SEPARATORS, repeat=3):
        domain = f"例え{a}one{b}two{c}example"
        assert domain.encode("idna") == b"xn--r8jz45g.one.two.example"
        address = f"利用者@{domain}"
        source = f"Contact <{address}>.\r\n"
        found = EmailDetector().find(source)
        assert [entity.value for entity in found] == [address]
        assert source[found[0].span.start : found[0].span.end] == address
        masker = Masker()
        masked = masker.mask(source)
        assert masked == "Contact <⟨EMAIL_1⟩>.\r\n"
        assert masker.restore(masked, tolerant=False) == source
        stream = Restorer(masker.vault)
        assert "".join(stream.feed(char) for char in masked) + stream.flush() == source


@pytest.mark.parametrize("separator", SEPARATORS[1:])
@pytest.mark.parametrize("local", ["alice", "first!last", '"private name"', "利用者", "ａｌｉｃｅ"])
def test_complete_suffix_and_local_spelling_remain_in_vault(separator: str, local: str) -> None:
    address = f"{local}@example.org{separator}private.example"
    masker = Masker()
    assert masker.mask(address) == "⟨EMAIL_1⟩"
    assert [mapping.original for mapping in masker.vault.mappings()] == [address]
    assert masker.restore("⟨EMAIL_1⟩") == address


@pytest.mark.parametrize("separator", SEPARATORS[1:])
@pytest.mark.parametrize(
    "suffix",
    ["_private", "+private", "-", ".123", "." + "a" * 64, "\u200bprivate", ".example.org"],
)
def test_malformed_domain_beyond_ascii_prefix_is_never_partially_masked(
    separator: str, suffix: str
) -> None:
    address = f"alice@example.org{separator}{suffix}"
    assert EmailDetector().find(address) == []
    assert Masker().mask(address) == address


@pytest.mark.parametrize("separator", SEPARATORS)
def test_final_separator_is_prose_punctuation(separator: str) -> None:
    assert Masker().mask(f"連絡先 alice@example.org{separator}") == f"連絡先 ⟨EMAIL_1⟩{separator}"


def test_equivalent_domain_spellings_remain_distinct_reversible_values() -> None:
    addresses = [f"alice@example{dot}org" for dot in SEPARATORS]
    masker = Masker()
    source = " / ".join(addresses)
    masked = masker.mask(source)
    assert masked == " / ".join(f"⟨EMAIL_{i}⟩" for i in range(1, 5))
    assert [mapping.original for mapping in masker.vault.mappings()] == addresses
    assert masker.restore(masked) == source
