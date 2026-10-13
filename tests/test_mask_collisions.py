"""Literal source text must not acquire another person's identity during restoration."""

from pathlib import Path

import pytest

from veil import Masker, PlaceholderSurrogates, RealisticSurrogates, Restorer, Vault, VaultError
from veil.backends.known_entities import KnownEntitiesBackend
from veil.cli import main
from veil.types import EntityType


@pytest.mark.parametrize("literal", ["⟨EMAIL_1⟩", "⟨email_1⟩", "x⟨eMaIl_1⟩y"])
def test_placeholder_examples_remain_literal(literal: str) -> None:
    text = f"Contact alice@example.org; keep {literal}."
    masker = Masker()
    masked = masker.mask(text)
    assert masked == f"Contact ⟨EMAIL_2⟩; keep {literal}."
    assert masker.restore(masked) == masker.restore(masked, tolerant=False) == text
    for cut in range(len(masked) + 1):
        stream = Restorer(masker.vault)
        assert stream.feed(masked[:cut]) + stream.feed(masked[cut:]) + stream.flush() == text


@pytest.mark.parametrize("reverse", [False, True])
def test_batch_reserves_literals_even_in_a_later_text(reverse: bool) -> None:
    texts = ["Contact alice@example.org", "Example: ⟨EMAIL_1⟩"]
    if reverse:
        texts.reverse()
    masker = Masker()
    masked = masker.mask_many(texts)
    assert [masker.restore(text) for text in masked] == texts
    assert "⟨EMAIL_2⟩" in " ".join(masked)
    assert len(masker.vault) == 1


def test_batch_reservations_do_not_join_separate_source_boundaries() -> None:
    texts = ["Contact alice@example.org", "⟨EMAIL_", "1⟩"]
    masker = Masker()
    masked = masker.mask_many(texts)
    assert masked == ["Contact ⟨EMAIL_1⟩", "⟨EMAIL_", "1⟩"]
    assert [masker.restore(text) for text in masked] == texts


def test_custom_batch_reservations_keep_normalized_literals_inside_a_source() -> None:
    texts = ["Contact alice@example.org", "An example: WRAP\u00a0EMAIL\n1."]
    masker = Masker(surrogate_generator=PlaceholderSurrogates(template="Wrap {type} {n}"))
    masked = masker.mask_many(texts)
    assert masked == ["Contact Wrap EMAIL 2", texts[1]]
    assert [masker.restore(text) for text in masked] == texts


def test_realistic_email_cannot_recycle_another_source_address() -> None:
    text = "Contact alice@example.org or user1@example.org."
    masker = Masker(surrogate_generator=RealisticSurrogates())
    masked = masker.mask(text)
    assert all(original not in masked for original in masker.vault.originals())
    assert masker.restore(masked) == text


def test_realistic_name_reserves_case_and_wrapped_spellings() -> None:
    text = "Jordan Reyes met BLAIR\n ALDER."
    masker = Masker(
        surrogate_generator=RealisticSurrogates(),
        name_backends=[KnownEntitiesBackend(persons=["Jordan Reyes"])],
    )
    masked = masker.mask(text)
    assert "Casey Alder" in masked
    assert masker.restore(masked) == text


def test_a_previous_original_is_never_recycled_as_a_new_surrogate() -> None:
    masker = Masker(
        surrogate_generator=RealisticSurrogates(),
        name_backends=[KnownEntitiesBackend(persons=["Casey Alder", "Jordan Reyes"])],
    )
    assert masker.mask("Casey Alder") == "Blair Alder"
    assert masker.mask("Jordan Reyes") == "Dana Alder"


@pytest.mark.parametrize("text", ["Example: ⟨EMAIL_1⟩", "new@example.org and ⟨email_1⟩"])
def test_reused_vault_refuses_ambiguous_literals_without_committing(text: str) -> None:
    masker = Masker()
    old_masked = masker.mask("alice@example.org")
    before = masker.vault.to_json()
    with pytest.raises(VaultError, match="source text|restoration") as error:
        masker.mask(text)
    assert "alice@example.org" not in str(error.value)
    assert "new@example.org" not in str(error.value)
    assert masker.vault.to_json() == before
    assert masker.restore(old_masked) == "alice@example.org"
    assert masker.mask("another@example.org") == "⟨EMAIL_2⟩"


def test_batch_failure_preserves_counters_and_all_earlier_mappings() -> None:
    masker = Masker()
    masker.mask("alice@example.org")
    before = masker.vault.to_json()
    with pytest.raises(VaultError):
        masker.mask_many(["new@example.org", "⟨EMAIL_1⟩"])
    assert masker.vault.to_json() == before
    assert masker.mask("new@example.org") == "⟨EMAIL_2⟩"


def test_bounded_unusable_generator_does_not_consume_the_vault() -> None:
    masker = Masker(surrogate_generator=PlaceholderSurrogates(template="literal"))
    with pytest.raises(VaultError, match="1024 attempts"):
        masker.mask("alice@example.org and literal")
    assert len(masker.vault) == 0


def test_detected_generator_failure_rolls_back_earlier_entities() -> None:
    class Fails:
        def generate(self, entity_type: EntityType, original: str, index: int) -> str:
            if index == 2:
                raise RuntimeError("controlled generator failure")
            return "TOKEN"

    masker = Masker(surrogate_generator=Fails())
    with pytest.raises(RuntimeError, match="controlled"):
        masker.mask("alice@example.org and bob@example.org")
    assert len(masker.vault) == 0


def test_cli_rejection_does_not_replace_output_or_saved_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    masker = Masker()
    masker.mask("alice@example.org")
    vault = tmp_path / "vault.json"
    masker.vault.save(str(vault))
    source = tmp_path / "source.txt"
    source.write_text("new@example.org and literal ⟨EMAIL_1⟩", encoding="utf-8")
    output = tmp_path / "out.txt"
    output.write_bytes(b"retained output")
    before = vault.read_bytes()
    assert main(["mask", str(source), "--vault", str(vault), "-o", str(output)]) == 2
    assert vault.read_bytes() == before
    assert output.read_bytes() == b"retained output"
    captured = capsys.readouterr()
    assert not captured.out
    assert "new@example.org" not in captured.err and "alice@example.org" not in captured.err
    assert Vault.load(str(vault)).to_json() == masker.vault.to_json()
