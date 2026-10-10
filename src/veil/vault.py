"""The vault: the original-value <-> surrogate mapping for one session.

**Threat model, stated honestly.** The vault is what makes masking
*reversible*, which means it is also the single artifact that can undo
veil's protection: anyone who reads it can de-anonymize the masked text.
veil treats it accordingly:

- In memory by default. Nothing touches disk unless you call
  :meth:`Vault.to_json` / :meth:`Vault.save` yourself.
- JSON serialization is plaintext by design (so you can inspect, diff, or
  hand-audit it) — **do not** commit it, log it, or send it anywhere the
  masked prompt itself isn't already allowed to go.
- The optional Fernet encryption (the ``vault-crypto`` extra, i.e. ``cryptography``)
  protects a vault *at rest* (on disk, in object storage) against someone
  who obtains the file but not the key. It does **not** protect against a
  compromised process that holds both the vault and the key in memory, and
  it does not provide forward secrecy, key rotation, or audit logging —
  those are your application's job. Store the key separately from the
  vault (a secrets manager, not the same disk directory).
- veil never phones home and never transmits the vault anywhere.

Restoration only works while the vault used to mask a given conversation is
kept alive (in memory, or reloaded from its saved JSON) for that
conversation's duration.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from veil._files import atomic_write_text
from veil.surrogates import SurrogateGenerator
from veil.types import EntityType, Mapping


class VaultError(Exception):
    """Raised for vault serialization/deserialization/crypto failures."""


MAX_SURROGATE_ATTEMPTS = 1024


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            # Keys can themselves contain private data. Never echo them here.
            raise VaultError("vault JSON contains a duplicate object key")
        result[key] = value
    return result


def _nonempty_text(value: Any, description: str) -> None:
    if not isinstance(value, str) or not value:
        raise VaultError(f"{description} must be a nonempty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise VaultError(f"{description} contains an unpaired Unicode surrogate") from exc


@dataclass
class Vault:
    """Bidirectional original<->surrogate map, consistent within a session."""

    _by_original: dict[tuple[EntityType, str], Mapping] = field(default_factory=dict)
    _by_surrogate: dict[str, Mapping] = field(default_factory=dict)
    _counters: dict[EntityType, int] = field(default_factory=dict)
    # Lookup structures derived from the mappings (the restore tries). Emptied
    # whenever a mapping is added, so a restore never works from a stale one.
    _derived: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Roll back library-owned state if preparing a masked request fails."""
        before = (
            self._by_original.copy(),
            self._by_surrogate.copy(),
            self._counters.copy(),
            self._derived.copy(),
        )
        try:
            yield
        except BaseException:
            self._by_original, self._by_surrogate, self._counters, self._derived = before
            raise

    def get_or_create(
        self,
        entity_type: EntityType,
        original: str,
        generator: SurrogateGenerator,
        detector: str = "",
        *,
        available: Callable[[str], bool] | None = None,
    ) -> str:
        """Return the existing surrogate for ``original``, minting one if new.

        ``available`` can reserve source literals. An unavailable existing
        mapping raises VaultError; established identities are never reassigned.
        """
        _nonempty_text(original, "original")
        key = (entity_type, original)
        existing = self._by_original.get(key)
        if existing is not None:
            if available is not None and not available(existing.surrogate):
                raise VaultError(
                    "an existing surrogate conflicts with source text; "
                    "use a fresh vault to remask the complete input"
                )
            return existing.surrogate

        index = self._counters.get(entity_type, 0)
        for _ in range(MAX_SURROGATE_ATTEMPTS):
            index += 1
            surrogate = generator.generate(entity_type, original, index)
            _nonempty_text(surrogate, "generated surrogate")
            if (
                surrogate != original
                and surrogate not in self._by_surrogate
                and (available is None or available(surrogate))
            ):
                break
        else:
            raise VaultError(
                "surrogate generator could not produce an available, distinct replacement after "
                f"{MAX_SURROGATE_ATTEMPTS} attempts; use numbered placeholders"
            )

        mapping = Mapping(
            type=entity_type, original=original, surrogate=surrogate, first_seen=detector
        )
        self._by_original[key] = mapping
        self._by_surrogate[surrogate] = mapping
        self._counters[entity_type] = index
        self._derived.clear()
        return surrogate

    def lookup_surrogate(self, surrogate: str) -> Mapping | None:
        return self._by_surrogate.get(surrogate)

    def lookup_original(self, entity_type: EntityType, original: str) -> Mapping | None:
        return self._by_original.get((entity_type, original))

    def surrogates(self) -> list[str]:
        """All surrogate strings, longest first (useful for restore matching)."""
        return sorted(self._by_surrogate.keys(), key=len, reverse=True)

    def originals(self) -> list[str]:
        """All original values that should never leak into outgoing text."""
        return [m.original for m in self._by_original.values()]

    def mappings(self) -> list[Mapping]:
        return list(self._by_original.values())

    def __len__(self) -> int:
        return len(self._by_original)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "mappings": [
                {
                    "type": m.type.value,
                    "original": m.original,
                    "surrogate": m.surrogate,
                    "detector": m.first_seen,
                }
                for m in self._by_original.values()
            ],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Vault:
        entries = data.get("mappings") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise VaultError("vault data must be an object with a 'mappings' list")
        version = data.get("version", 1)  # accept unversioned legacy vaults
        if type(version) is not int or version != 1:
            raise VaultError("unsupported vault version; expected version 1")
        vault = cls()
        for n, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise VaultError(f"vault mapping {n} is not an object")
            for key in ("type", "original", "surrogate"):
                _nonempty_text(entry.get(key), f"vault mapping {n}: {key}")
            try:
                etype = EntityType(entry["type"])
            except ValueError as exc:
                raise VaultError(f"vault mapping {n}: unknown entity type") from exc
            detector = entry.get("detector", "")
            if not isinstance(detector, str):
                raise VaultError(f"vault mapping {n}: detector must be a string")
            if (etype, entry["original"]) in vault._by_original:
                raise VaultError(f"vault mapping {n}: duplicate original for this entity type")
            if entry["surrogate"] in vault._by_surrogate:
                raise VaultError(f"vault mapping {n}: duplicate surrogate")
            if entry["surrogate"] == entry["original"]:
                raise VaultError(f"vault mapping {n}: surrogate must differ from its original")
            mapping = Mapping(
                type=etype,
                original=entry["original"],
                surrogate=entry["surrogate"],
                first_seen=detector,
            )
            vault._by_original[(etype, mapping.original)] = mapping
            vault._by_surrogate[mapping.surrogate] = mapping
            vault._counters[etype] = vault._counters.get(etype, 0) + 1
        return vault

    @classmethod
    def from_json(cls, data: str) -> Vault:
        try:
            parsed = json.loads(data, object_pairs_hook=_unique_object)
        except json.JSONDecodeError as exc:
            raise VaultError(
                f"invalid vault JSON at line {exc.lineno}, column {exc.colno}"
            ) from exc
        except RecursionError as exc:
            raise VaultError("vault JSON is nested too deeply") from exc
        return cls.from_dict(parsed)

    def save(self, path: str) -> None:
        """Atomically replace a vault, with owner-only permissions on POSIX.

        A temporary sibling keeps a failed write from truncating the only copy
        of a conversation's mappings. Symlinks are refused rather than followed.
        This does not encrypt the file or coordinate concurrent writers.
        """
        atomic_write_text(path, self.to_json())

    @classmethod
    def load(cls, path: str) -> Vault:
        with open(path, encoding="utf-8") as f:
            return cls.from_json(f.read())

    # -- Optional at-rest encryption (requires the 'vault-crypto' extra) --

    def encrypt(self, key: bytes) -> bytes:
        """Encrypt the vault's JSON with Fernet (AES-128-CBC + HMAC). See
        the module docstring for what this does and doesn't protect against.
        """
        try:
            from cryptography.fernet import Fernet  # noqa: PLC0415
        except ImportError as exc:
            raise VaultError(
                "encrypt() requires the 'cryptography' package (veil's 'vault-crypto' extra): "
                "pip install 'veil-pii[vault-crypto]'"
            ) from exc
        try:
            cipher = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise VaultError("invalid Fernet key; use Vault.generate_key()") from exc
        return cipher.encrypt(self.to_json(indent=None).encode("utf-8"))

    @classmethod
    def decrypt(cls, token: bytes, key: bytes) -> Vault:
        try:
            from cryptography.fernet import Fernet, InvalidToken  # noqa: PLC0415
        except ImportError as exc:
            raise VaultError(
                "decrypt() requires the 'cryptography' package (veil's 'vault-crypto' extra): "
                "pip install 'veil-pii[vault-crypto]'"
            ) from exc
        try:
            cipher = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise VaultError("invalid Fernet key; use Vault.generate_key()") from exc
        try:
            plaintext = cipher.decrypt(token)
        except InvalidToken as exc:
            raise VaultError("wrong key, or vault data is corrupted/tampered") from exc
        try:
            text = plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise VaultError("decrypted vault is not valid UTF-8") from exc
        return cls.from_json(text)

    @staticmethod
    def generate_key() -> bytes:
        try:
            from cryptography.fernet import Fernet  # noqa: PLC0415
        except ImportError as exc:
            raise VaultError(
                "generate_key() requires the 'cryptography' package (veil's 'vault-crypto' extra): "
                "pip install 'veil-pii[vault-crypto]'"
            ) from exc
        return Fernet.generate_key()
