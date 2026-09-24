"""The pluggable interface for name/organization/location detection.

Free-text detection of names is a hard NLP problem (see
:mod:`veil.backends.spacy_backend` for the honest accuracy caveat). Any
backend — a wrapped NER model, a lookup against your CRM, a regex over a
gazetteer — can be used as long as it implements :meth:`NameBackend.find`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from veil.types import Entity


@runtime_checkable
class NameBackend(Protocol):
    """Finds PERSON / ORG / LOCATION entities in free text."""

    name: str

    def find(self, text: str) -> list[Entity]:
        """Return non-overlapping entities found in ``text``, in span order."""
        ...
