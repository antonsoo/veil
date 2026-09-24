"""The detector interface every built-in and pluggable detector implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from veil.types import Entity


@runtime_checkable
class Detector(Protocol):
    """A detector finds occurrences of one kind of sensitive value in text.

    Implementations should be pure functions of ``text`` (no I/O, no shared
    mutable state) so they can be composed, tested in isolation, and run in
    any order. ``name`` should be a short, stable identifier (e.g.
    ``"email"``) used for provenance in :class:`veil.types.Entity`.
    """

    name: str

    def find(self, text: str) -> list[Entity]:
        """Return non-overlapping entities found in ``text``, in span order."""
        ...
