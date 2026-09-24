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
- The optional Fernet encryption (``pip install "veil-pii[vault-crypto]"``)
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
from dataclasses import dataclass, field
from typing import Any

from veil.surrogates import SurrogateGenerator
from veil.types import EntityType, Mapping


class VaultError(Exception):
    """Raised for vault serialization/deserialization/crypto failures."""


@dataclass
class Vault:
    """Bidirectional original<->surrogate map, consistent within a session."""

    _by_original: dict[tuple[EntityType, str], Mapping] = field(default_factory=dict)
    _by_surrogate: dict[str, Mapping] = field(default_factory=dict)
    _counters: dict[EntityType, int] = field(default_factory=dict)

    def get_or_create(
        self,
        entity_type: EntityType,
        original: str,
        generator: SurrogateGenerator,
        detector: str = "",
    ) -> str:
        """Return the existing surrogate for ``original``, minting one if new."""
        key = (entity_type, original)
        existing = self._by_original.get(key)
        if existing is not None:
            return existing.surrogate

        index = self._counters.get(entity_type, 0) + 1
        self._counters[entity_type] = index
        surrogate = generator.generate(entity_type, original, index)
        # Extremely unlikely, but guard against a generator producing a
        # surrogate that collides with an existing one for another value.
        while surrogate in self._by_surrogate:
            index += 1
            self._counters[entity_type] = index
            surrogate = generator.generate(entity_type, original, index)

        mapping = Mapping(
            type=entity_type, original=original, surrogate=surrogate, first_seen=detector
        )
        self._by_original[key] = mapping
        self._by_surrogate[surrogate] = mapping
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
        vault = cls()
        for entry in data.get("mappings", []):
            try:
                etype = EntityType(entry["type"])
            except ValueError as exc:
                raise VaultError(f"unknown entity type in vault data: {entry['type']!r}") from exc
            mapping = Mapping(
                type=etype,
                original=entry["original"],
                surrogate=entry["surrogate"],
                first_seen=entry.get("detector", ""),
            )
            vault._by_original[(etype, mapping.original)] = mapping
            vault._by_surrogate[mapping.surrogate] = mapping
            vault._counters[etype] = vault._counters.get(etype, 0) + 1
        return vault

    @classmethod
    def from_json(cls, data: str) -> Vault:
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise VaultError(f"invalid vault JSON: {exc}") from exc
        return cls.from_dict(parsed)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

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
                "encrypt() requires the 'vault-crypto' extra: "
                'pip install "veil-pii[vault-crypto]"'
            ) from exc
        return Fernet(key).encrypt(self.to_json(indent=None).encode("utf-8"))

    @classmethod
    def decrypt(cls, token: bytes, key: bytes) -> Vault:
        try:
            from cryptography.fernet import Fernet, InvalidToken  # noqa: PLC0415
        except ImportError as exc:
            raise VaultError(
                "decrypt() requires the 'vault-crypto' extra: "
                'pip install "veil-pii[vault-crypto]"'
            ) from exc
        try:
            plaintext = Fernet(key).decrypt(token)
        except InvalidToken as exc:
            raise VaultError("wrong key, or vault data is corrupted/tampered") from exc
        return cls.from_json(plaintext.decode("utf-8"))

    @staticmethod
    def generate_key() -> bytes:
        try:
            from cryptography.fernet import Fernet  # noqa: PLC0415
        except ImportError as exc:
            raise VaultError(
                "generate_key() requires the 'vault-crypto' extra: "
                'pip install "veil-pii[vault-crypto]"'
            ) from exc
        return Fernet.generate_key()
