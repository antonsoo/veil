import pytest

from veil.surrogates import PlaceholderSurrogates
from veil.types import EntityType
from veil.vault import Vault, VaultError


def test_get_or_create_is_consistent_for_same_value() -> None:
    vault = Vault()
    gen = PlaceholderSurrogates()
    s1 = vault.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    s2 = vault.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    assert s1 == s2
    assert len(vault) == 1


def test_get_or_create_assigns_distinct_surrogates_per_value() -> None:
    vault = Vault()
    gen = PlaceholderSurrogates()
    s1 = vault.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    s2 = vault.get_or_create(EntityType.EMAIL, "c@d.com", gen)
    assert s1 != s2


def test_same_value_different_type_gets_own_entry() -> None:
    vault = Vault()
    gen = PlaceholderSurrogates()
    vault.get_or_create(EntityType.PERSON, "Cascade", gen)
    vault.get_or_create(EntityType.ORG, "Cascade", gen)
    assert len(vault) == 2


def test_lookup_surrogate_and_original_round_trip() -> None:
    vault = Vault()
    gen = PlaceholderSurrogates()
    surrogate = vault.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    mapping = vault.lookup_surrogate(surrogate)
    assert mapping is not None
    assert mapping.original == "a@b.com"
    mapping2 = vault.lookup_original(EntityType.EMAIL, "a@b.com")
    assert mapping2 is not None
    assert mapping2.surrogate == surrogate


def test_json_round_trip() -> None:
    vault = Vault()
    gen = PlaceholderSurrogates()
    vault.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    vault.get_or_create(EntityType.PHONE, "202-555-0143", gen)

    restored = Vault.from_json(vault.to_json())
    assert len(restored) == len(vault)
    assert (
        restored.lookup_original(EntityType.EMAIL, "a@b.com").surrogate
        == vault.lookup_original(EntityType.EMAIL, "a@b.com").surrogate
    )


def test_from_json_rejects_malformed_json() -> None:
    with pytest.raises(VaultError):
        Vault.from_json("{not valid json")


def test_from_json_rejects_unknown_entity_type() -> None:
    with pytest.raises(VaultError):
        Vault.from_json(
            '{"version": 1, "mappings": [{"type": "BOGUS", "original": "x", "surrogate": "y"}]}'
        )


def test_save_and_load_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    vault = Vault()
    gen = PlaceholderSurrogates()
    vault.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    path = tmp_path / "vault.json"
    vault.save(str(path))
    loaded = Vault.load(str(path))
    assert len(loaded) == 1


def test_counter_resumes_after_loading_from_json() -> None:
    vault = Vault()
    gen = PlaceholderSurrogates()
    vault.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    restored = Vault.from_json(vault.to_json())
    # A brand-new value added after reload should not collide with index 1.
    new_surrogate = restored.get_or_create(EntityType.EMAIL, "c@d.com", gen)
    assert new_surrogate != restored.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    assert "2" in new_surrogate or new_surrogate not in (
        vault.lookup_original(EntityType.EMAIL, "a@b.com").surrogate,
    )


def test_encrypt_decrypt_round_trip_requires_extra() -> None:
    pytest.importorskip("cryptography")
    vault = Vault()
    gen = PlaceholderSurrogates()
    vault.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    key = Vault.generate_key()
    token = vault.encrypt(key)
    decrypted = Vault.decrypt(token, key)
    assert len(decrypted) == 1
    assert decrypted.lookup_original(EntityType.EMAIL, "a@b.com") is not None


def test_decrypt_with_wrong_key_raises() -> None:
    pytest.importorskip("cryptography")
    vault = Vault()
    gen = PlaceholderSurrogates()
    vault.get_or_create(EntityType.EMAIL, "a@b.com", gen)
    key = Vault.generate_key()
    wrong_key = Vault.generate_key()
    token = vault.encrypt(key)
    with pytest.raises(VaultError):
        Vault.decrypt(token, wrong_key)
