"""The masking pipeline: text -> (masked text, vault).

Ties together detectors, name backends, a surrogate generator, and a vault.
Detector results are pooled, overlaps resolved (higher confidence wins,
ties broken by longer span, then earliest detector), and replaced in
reading order, so the first value of a type in a text is numbered 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from veil._spans import DisjointSpans
from veil.backends.base import NameBackend
from veil.detectors import default_detectors
from veil.detectors.base import Detector
from veil.restore import restore_exact, restore_tolerant
from veil.surrogates import PlaceholderSurrogates, SurrogateGenerator
from veil.types import Entity
from veil.vault import Vault


def _resolve_overlaps(entities: list[Entity]) -> list[Entity]:
    """Greedily keep non-overlapping entities, preferring higher confidence
    then longer span then earlier start, matching how a careful reviewer
    would break ties by hand.
    """
    ranked = sorted(
        entities,
        key=lambda e: (-e.confidence, -len(e.span), e.span.start),
    )
    kept: list[Entity] = []
    taken = DisjointSpans()
    for entity in ranked:
        if taken.overlaps(entity.span):
            continue
        taken.add(entity.span)
        kept.append(entity)
    kept.sort(key=lambda e: e.span.start)
    return kept


@dataclass
class Masker:
    """Configure once, call :meth:`mask` per message. Reuse the same
    :class:`Masker` (and its vault) across a whole conversation so repeated
    values map to the same surrogate throughout.
    """

    detectors: list[Detector] = field(default_factory=default_detectors)
    name_backends: list[NameBackend] = field(default_factory=list)
    surrogate_generator: SurrogateGenerator = field(default_factory=PlaceholderSurrogates)
    vault: Vault = field(default_factory=Vault)

    def find_entities(self, text: str) -> list[Entity]:
        found: list[Entity] = []
        for detector in self.detectors:
            found.extend(detector.find(text))
        for backend in self.name_backends:
            found.extend(backend.find(text))
        return _resolve_overlaps(found)

    def mask(self, text: str) -> str:
        parts: list[str] = []
        pos = 0
        for entity in self.find_entities(text):
            surrogate = self.vault.get_or_create(
                entity.type, entity.value, self.surrogate_generator, entity.detector
            )
            parts.append(text[pos : entity.span.start])
            parts.append(surrogate)
            pos = entity.span.end
        parts.append(text[pos:])
        return "".join(parts)

    def restore(self, text: str, *, tolerant: bool = True) -> str:
        """Restore surrogates in ``text`` using this masker's vault.

        ``tolerant=True`` (the default) also catches case changes and
        possessives a model commonly introduces; pass ``False`` for
        byte-exact matching only. For a token stream, use
        :class:`veil.restore.Restorer` directly instead.
        """
        return restore_tolerant(text, self.vault) if tolerant else restore_exact(text, self.vault)
