"""Failures here can silently change identity or strand a masked conversation."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from veil import Masker
from veil.restore import restore_exact
from veil.surrogates import PlaceholderSurrogates, RealisticSurrogates
from veil.types import EntityType
from veil.vault import MAX_SURROGATE_ATTEMPTS, Vault, VaultError


def entry(original: str = "alice@example.com", surrogate: str = "TOKEN") -> dict[str, str]:
    return {"type": "EMAIL", "original": original, "surrogate": surrogate}


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"version": 2, "mappings": []},
        {"version": True, "mappings": []},
        {"version": 1.0, "mappings": []},
        {"mappings": [entry(), entry("bob@example.com")]},
        {"mappings": [entry(), entry(surrogate="SECOND")]},
        {"mappings": [entry(), entry()]},
        {"mappings": [entry("", "TOKEN")]},
        {"mappings": [entry("same", "same")]},
        {"mappings": [entry(surrogate="\ud800")]},
        {"mappings": [{**entry(), "detector": 7}]},
    ],
)
def test_ambiguous_or_unsupported_vaults_are_rejected(data: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(VaultError) as exc:
        Vault.from_dict(data)
    assert "alice@example.com" not in str(exc.value)
    assert "bob@example.com" not in str(exc.value)


@pytest.mark.parametrize(
    "text",
    [
        '{"mappings": [], "mappings": []}',
        '{"mappings": [{"type":"EMAIL", "original":"alice@example.com", '
        '"surrogate":"FIRST", "surrogate":"SECOND"}]}',
    ],
)
def test_duplicate_json_keys_are_not_silently_overwritten(text: str) -> None:
    with pytest.raises(VaultError, match="duplicate object key"):
        Vault.from_json(text)


def test_lookup_cannot_mutate_the_cached_restore_index() -> None:
    vault = Vault.from_dict({"mappings": [entry()]})
    assert restore_exact("TOKEN", vault) == "alice@example.com"
    mapping = vault.mappings()[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        mapping.original = "someone-else@example.com"  # type: ignore[misc]
    assert restore_exact("TOKEN", vault) == "alice@example.com"


@pytest.mark.parametrize(
    "kind,count", [(EntityType.ORG, 75), (EntityType.PERSON, 580), (EntityType.PHONE, 805)]
)
def test_realistic_pools_fall_back_without_reusing_a_surrogate(
    kind: EntityType, count: int
) -> None:
    vault = Vault()
    generator = RealisticSurrogates()
    originals = [f"original-{i}" for i in range(count)]
    surrogates = [vault.get_or_create(kind, value, generator) for value in originals]
    assert len(set(surrogates)) == count
    assert surrogates[-1].startswith(f"⟨{kind.value}_")
    assert restore_exact(" | ".join(surrogates), vault) == " | ".join(originals)
    reloaded = Vault.from_json(vault.to_json())
    assert reloaded.get_or_create(kind, "another", generator) not in surrogates


def test_an_original_that_looks_like_a_fake_is_still_masked() -> None:
    masker = Masker(surrogate_generator=RealisticSurrogates())
    masked = masker.mask("user1@example.org")
    assert "user1@example.org" not in masked
    assert masker.restore(masked, tolerant=False) == "user1@example.org"


def test_constant_generator_fails_with_a_bound_and_preserves_the_vault() -> None:
    vault = Vault()
    generator = PlaceholderSurrogates(template="TOKEN")
    vault.get_or_create(EntityType.EMAIL, "first", generator)
    before = vault.to_json()
    with pytest.raises(VaultError, match=str(MAX_SURROGATE_ATTEMPTS)):
        vault.get_or_create(EntityType.EMAIL, "second", generator)
    assert vault.to_json() == before
    assert vault.get_or_create(EntityType.EMAIL, "second", PlaceholderSurrogates()) == "⟨EMAIL_2⟩"


def test_empty_generator_is_rejected_without_changing_the_vault() -> None:
    vault = Vault()
    with pytest.raises(VaultError, match="nonempty"):
        vault.get_or_create(EntityType.PERSON, "Alice", PlaceholderSurrogates(template=""))
    assert len(vault) == 0


def test_failed_atomic_save_keeps_the_previous_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "vault.json"
    vault = Vault.from_dict({"mappings": [entry()]})
    vault.save(str(path))
    previous = path.read_bytes()
    vault.get_or_create(EntityType.EMAIL, "new", PlaceholderSurrogates())

    def fail_replace(*args: object) -> None:
        raise OSError("simulated failed rename")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        vault.save(str(path))
    assert path.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["vault.json"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits")
def test_plaintext_vault_is_private_even_when_replacing_a_public_file(tmp_path: Path) -> None:
    path = tmp_path / "vault.json"
    path.touch(mode=0o644)
    Vault.from_dict({"mappings": [entry()]}).save(str(path))
    assert path.stat().st_mode & 0o777 == 0o600


def test_save_does_not_follow_a_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "original"
    target.write_text("keep")
    alias = tmp_path / "vault.json"
    alias.symlink_to(target)
    with pytest.raises(OSError, match="symbolic link"):
        Vault().save(str(alias))
    assert target.read_text() == "keep"


def test_deep_json_reports_a_vault_error() -> None:
    with pytest.raises(VaultError):
        Vault.from_json("[" * 2000 + "]" * 2000)


def test_invalid_crypto_keys_and_decoded_text_report_vault_errors() -> None:
    fernet = pytest.importorskip("cryptography.fernet")
    with pytest.raises(VaultError, match="invalid Fernet key"):
        Vault().encrypt(b"bad-key")
    with pytest.raises(VaultError, match="invalid Fernet key"):
        Vault.decrypt(b"token", b"bad-key")
    key = Vault.generate_key()
    encrypted = fernet.Fernet(key).encrypt(b"\xff")
    with pytest.raises(VaultError, match="not valid UTF-8"):
        Vault.decrypt(encrypted, key)
