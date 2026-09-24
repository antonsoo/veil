"""Pluggable backends for name/organization/location detection.

``SpacyBackend`` is imported lazily (only on attribute access) so that
importing :mod:`veil.backends` never requires the optional ``spacy`` extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from veil.backends.base import NameBackend
from veil.backends.known_entities import KnownEntitiesBackend

if TYPE_CHECKING:
    from veil.backends.spacy_backend import SpacyBackend

__all__ = ["NameBackend", "KnownEntitiesBackend", "SpacyBackend"]


def __getattr__(attr: str) -> Any:
    if attr == "SpacyBackend":
        from veil.backends.spacy_backend import SpacyBackend as _SpacyBackend

        return _SpacyBackend
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")
