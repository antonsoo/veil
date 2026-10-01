from veil.backends.known_entities import KnownEntitiesBackend
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


def test_restore_tolerant_never_rescans_a_restored_value() -> None:
    # "Blair Alder" is a real person here and also the fake name handed to
    # Jordan Reyes. Restoring the fake must not then rewrite the real one.
    backend = KnownEntitiesBackend(persons=["Jordan Reyes", "Blair Alder"])
    m = Masker(surrogate_generator=RealisticSurrogates(), name_backends=[backend])
    text = "Jordan Reyes met Blair Alder."
    masked = m.mask(text)
    assert masked == "Blair Alder met Casey Alder."
    assert restore_tolerant(masked, m.vault) == text


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
