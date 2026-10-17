import unicodedata

import pytest

from veil.masker import Masker
from veil.restore import restore_exact, restore_tolerant
from veil.surrogates import PlaceholderSurrogates, RealisticSurrogates
from veil.types import EntityType
from veil.vault import Vault


def test_restore_exact_basic() -> None:
    m = Masker()
    text = "Email alice@example.com now."
    masked = m.mask(text)
    assert restore_exact(masked, m.vault) == text


def test_restore_exact_does_not_touch_unmasked_text() -> None:
    vault = Vault()
    assert restore_exact("nothing to restore here", vault) == "nothing to restore here"


def test_restore_tolerant_handles_lowercased_surrogate() -> None:
    vault = Vault()
    gen = PlaceholderSurrogates()
    vault.get_or_create(EntityType.PERSON, "Alice Johnson", gen, "known_entities")
    # Placeholder text as the model might echo it back, miscased.
    model_reply = "Thanks, ⟨person_1⟩! We'll follow up."
    assert restore_tolerant(model_reply, vault) == "Thanks, Alice Johnson! We'll follow up."


def test_restore_tolerant_handles_possessive() -> None:
    m = Masker(surrogate_generator=RealisticSurrogates())
    m.vault.get_or_create(EntityType.PERSON, "Alice Johnson", m.surrogate_generator)
    fake_name = m.vault.lookup_original(EntityType.PERSON, "Alice Johnson").surrogate
    model_reply = f"{fake_name}'s account was updated."
    assert restore_tolerant(model_reply, m.vault) == "Alice Johnson's account was updated."


def test_restore_tolerant_handles_line_break_split_name() -> None:
    m = Masker(surrogate_generator=RealisticSurrogates())
    m.vault.get_or_create(EntityType.PERSON, "Alice Johnson", m.surrogate_generator)
    fake_name = m.vault.lookup_original(EntityType.PERSON, "Alice Johnson").surrogate
    first, last = fake_name.split(" ")
    model_reply = f"Regards,\n{first}\n{last}"
    assert restore_tolerant(model_reply, m.vault) == "Regards,\nAlice Johnson"


def test_restore_tolerant_does_not_touch_unrelated_substring() -> None:
    # A realistic (plain-word) surrogate embedded with no separating
    # whitespace inside a longer, unrelated word must not be restored:
    # neither the exact pass (no literal "Avery Alder" substring, since
    # there's no space) nor the tolerant word-boundary regex should fire.
    m = Masker(surrogate_generator=RealisticSurrogates())
    m.vault.get_or_create(EntityType.PERSON, "Alice Johnson", m.surrogate_generator)
    first, last = m.vault.lookup_original(EntityType.PERSON, "Alice Johnson").surrogate.split(" ")
    text = f"prefix{first}{last}suffix"
    assert restore_tolerant(text, m.vault) == text


def test_restore_tolerant_is_superset_of_exact() -> None:
    m = Masker()
    text = "Contact alice@example.com or +1 202-555-0143."
    masked = m.mask(text)
    assert restore_tolerant(masked, m.vault) == restore_exact(masked, m.vault) == text


def _castillo_vault() -> Vault:
    return Vault.from_dict(
        {
            "version": 1,
            "mappings": [
                {"type": "PERSON", "original": "Jordan Alvarez", "surrogate": "Avery Castillo"}
            ],
        }
    )


@pytest.mark.parametrize("normalization", ["NFC", "NFD"])
def test_recased_accented_surname_is_not_a_fuzzy_surrogate(normalization: str) -> None:
    # In NFD the final ó is o + U+0301. Restoring the unaccented prefix
    # would insert a private identity into a different person's name.
    reply = unicodedata.normalize(normalization, "Ask avery castilló about the booking.")
    assert restore_tolerant(reply, _castillo_vault()) == reply


@pytest.mark.parametrize("mark", ["\u0301", "\u093e", "\u20dd"])
@pytest.mark.parametrize("at_start", [False, True])
def test_fuzzy_match_cannot_cut_through_an_attached_unicode_mark(mark: str, at_start: bool) -> None:
    # Nonspacing, spacing and enclosing marks are boundary controls, not
    # claims that these mixed-script strings are ordinary personal names.
    reply = f"x{mark}avery castillo" if at_start else f"avery castillo{mark}x"
    assert restore_tolerant(reply, _castillo_vault()) == reply


def test_exact_substring_contract_is_unchanged_beside_a_combining_mark() -> None:
    reply = "prefixAvery Castillo\u0301suffix"
    expected = "prefixJordan Alvarez\u0301suffix"
    vault = _castillo_vault()
    assert restore_exact(reply, vault) == restore_tolerant(reply, vault) == expected


def test_restore_tolerant_never_rescans_a_restored_value() -> None:
    # "Blair Alder" is a real person here and also the fake name handed to
    # Jordan Reyes. Restoring the fake must not then rewrite the real one.
    # Such a legacy vault remains readable, though Masker now avoids minting
    # a replacement that is also present in the source.
    vault = Vault()
    gen = RealisticSurrogates()
    vault.get_or_create(EntityType.PERSON, "Jordan Reyes", gen)
    vault.get_or_create(EntityType.PERSON, "Blair Alder", gen)
    text = "Jordan Reyes met Blair Alder."
    assert restore_tolerant("Blair Alder met Casey Alder.", vault) == text


def test_restore_tolerant_restores_a_recased_placeholder_touching_other_text() -> None:
    vault = Vault()
    vault.get_or_create(EntityType.IPV4, "10.0.0.1", PlaceholderSurrogates(), "ip")
    assert restore_tolerant("host=⟨ipv4_1⟩:8080 and x⟨ipv4_1⟩y", vault) == (
        "host=10.0.0.1:8080 and x10.0.0.1y"
    )


def test_restore_sees_values_added_to_the_vault_after_an_earlier_restore() -> None:
    m = Masker()
    first = m.mask("alice@example.com")
    assert m.restore(first) == "alice@example.com"
    second = m.mask("bob@example.com")
    assert m.restore(f"{first} and {second}") == "alice@example.com and bob@example.com"
    assert m.restore(f"{first} and {second}", tolerant=False) == (
        "alice@example.com and bob@example.com"
    )
