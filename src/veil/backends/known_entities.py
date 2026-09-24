"""The "known entities" backend: exact matches against values you supply.

This is the backend to reach for first. Most applications already know the
customer's name, company, and city from their own database — that beats any
general-purpose NER model, which has to *guess* who's a person from context
alone. Matching is case-insensitive and word-boundary-aware, with longer
entries matched first so "Alice Johnson" wins over a lone "Alice".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from veil.types import Entity, EntityType, Span


@dataclass
class KnownEntitiesBackend:
    """Looks for exact, application-supplied names/orgs/locations.

    Example::

        backend = KnownEntitiesBackend(
            persons=["Alice Johnson"],
            orgs=["Acme Corp"],
            locations=["Springfield"],
        )
    """

    persons: list[str] = field(default_factory=list)
    orgs: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    name: str = "known_entities"

    def _entries(self) -> list[tuple[str, EntityType]]:
        entries = (
            [(v, EntityType.PERSON) for v in self.persons if v.strip()]
            + [(v, EntityType.ORG) for v in self.orgs if v.strip()]
            + [(v, EntityType.LOCATION) for v in self.locations if v.strip()]
        )
        # Longest-first so multi-word entries are matched before their
        # substrings (e.g. full name before first name alone).
        entries.sort(key=lambda pair: len(pair[0]), reverse=True)
        return entries

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        claimed: list[Span] = []
        for value, etype in self._entries():
            pattern = re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)", re.IGNORECASE)
            for m in pattern.finditer(text):
                span = Span(m.start(), m.end())
                if any(span.overlaps(c) for c in claimed):
                    continue
                claimed.append(span)
                out.append(
                    Entity(
                        type=etype,
                        value=m.group(0),
                        span=span,
                        detector=self.name,
                        confidence=1.0,
                    )
                )
        out.sort(key=lambda e: e.span.start)
        return out
