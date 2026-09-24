"""Property-based tests: streaming restore must equal non-streamed restore
for *any* way the same text is split into chunks. This is the guarantee
that makes :class:`~veil.restore.Restorer` safe to point at a live token
stream instead of a buffered response.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from veil.restore import Restorer, restore_exact
from veil.types import EntityType
from veil.vault import Vault

_gen_template = "⟨{type}_{n}⟩"


def _sample_vault() -> Vault:
    from veil.surrogates import PlaceholderSurrogates

    vault = Vault()
    gen = PlaceholderSurrogates()
    vault.get_or_create(EntityType.EMAIL, "alice@example.com", gen)
    vault.get_or_create(EntityType.PHONE, "+1 202-555-0143", gen)
    vault.get_or_create(EntityType.PERSON, "Alice Johnson", gen)
    vault.get_or_create(EntityType.CARD, "4111 1111 1111 1111", gen)
    return vault


def _chunks_from_cut_points(text: str, cuts: list[int]) -> list[str]:
    points = sorted({c % (len(text) + 1) for c in cuts})
    points = [0, *points, len(text)]
    return [text[a:b] for a, b in zip(points, points[1:], strict=False) if a != b or a == 0]


@given(
    cuts=st.lists(st.integers(min_value=0, max_value=500), min_size=0, max_size=40),
)
@settings(max_examples=200)
def test_streaming_matches_non_streamed_for_random_chunking(cuts: list[int]) -> None:
    vault = _sample_vault()
    text = "Hi ⟨PERSON_1⟩, please confirm ⟨EMAIL_1⟩ and ⟨PHONE_1⟩. Card on file: ⟨CARD_1⟩. Thanks!"
    expected = restore_exact(text, vault)

    restorer = Restorer(vault)
    pieces = []
    for chunk in _chunks_from_cut_points(text, cuts):
        pieces.append(restorer.feed(chunk))
    pieces.append(restorer.flush())
    assert "".join(pieces) == expected


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=200))
@settings(max_examples=100)
def test_streaming_is_identity_on_arbitrary_text_with_no_surrogates(text: str) -> None:
    vault = _sample_vault()
    restorer = Restorer(vault)
    out = restorer.feed(text) + restorer.flush()
    # As long as the arbitrary text doesn't happen to contain one of the
    # vault's surrogate strings verbatim, restoring is a no-op.
    if all(s not in text for s in vault.surrogates()):
        assert out == text


@given(st.integers(min_value=1, max_value=7))
@settings(max_examples=50)
def test_char_by_char_streaming_matches_non_streamed(chunk_size: int) -> None:
    vault = _sample_vault()
    text = "Dear ⟨PERSON_1⟩, your card ⟨CARD_1⟩ was charged."
    expected = restore_exact(text, vault)

    restorer = Restorer(vault)
    out = []
    for i in range(0, len(text), chunk_size):
        out.append(restorer.feed(text[i : i + chunk_size]))
    out.append(restorer.flush())
    assert "".join(out) == expected


def test_surrogate_split_exactly_at_chunk_boundary() -> None:
    vault = _sample_vault()
    restorer = Restorer(vault)
    out1 = restorer.feed("Hi ⟨PERS")
    out2 = restorer.feed("ON_1⟩, welcome.")
    out3 = restorer.flush()
    assert out1 + out2 + out3 == "Hi Alice Johnson, welcome."


def test_holds_back_minimal_prefix_only() -> None:
    vault = _sample_vault()
    restorer = Restorer(vault)
    # "Hi " is definitely not part of any surrogate and should be emitted
    # immediately; only the trailing partial-prefix should be held back.
    out = restorer.feed("Hi ⟨PERS")
    assert out == "Hi "


def test_partial_prefix_that_never_completes_flushes_as_literal_text() -> None:
    vault = _sample_vault()
    restorer = Restorer(vault)
    out1 = restorer.feed("almost ⟨PERSON_9")  # no such surrogate in vault
    out2 = restorer.flush()
    assert out1 + out2 == "almost ⟨PERSON_9"
