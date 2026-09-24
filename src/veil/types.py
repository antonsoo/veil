"""Shared data types used across detectors, surrogates, and the vault.

Kept dependency-free and immutable where practical so that the core package
has zero runtime dependencies and is safe to pass across threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EntityType(str, Enum):
    """Categories of sensitive value veil knows how to detect or accept.

    String-valued so surrogate tokens (e.g. ``EMAIL_1``) can be built
    directly from ``.value`` and so the vault serializes as plain JSON.
    """

    EMAIL = "EMAIL"
    PHONE = "PHONE"
    CARD = "CARD"
    IBAN = "IBAN"
    SSN = "SSN"
    IPV4 = "IPV4"
    IPV6 = "IPV6"
    URL_CREDENTIAL = "URL_CREDENTIAL"
    SECRET = "SECRET"
    DOB = "DOB"
    ADDRESS = "ADDRESS"
    PERSON = "PERSON"
    ORG = "ORG"
    LOCATION = "LOCATION"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True, slots=True)
class Span:
    """A half-open character range ``[start, end)`` in some source text."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span: start={self.start} end={self.end}")

    def __len__(self) -> int:
        return self.end - self.start

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True, slots=True)
class Entity:
    """One detected (or supplied) sensitive value, located in source text."""

    type: EntityType
    value: str
    span: Span
    detector: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")


@dataclass(slots=True)
class Mapping:
    """One entry in the vault: an original value bound to its surrogate."""

    type: EntityType
    original: str
    surrogate: str
    first_seen: str = field(default="")  # detector name, for provenance/debugging
