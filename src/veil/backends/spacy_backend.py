"""Optional spaCy NER backend for PERSON / ORG / LOCATION detection.

Requires the ``spacy`` extra (``pip install "veil-pii[spacy]"``) and a
downloaded model, e.g.::

    python -m spacy download en_core_web_sm

**Accuracy caveat, stated honestly:** we have not benchmarked spaCy's NER
against veil's synthetic corpus or any real data. Published spaCy
benchmarks (see the model's own model card) report entity-level F-scores
in the 0.80-0.90 range on news text for `en_core_web_sm`/`_trf`; PII in
support tickets, clinical notes, or chat transcripts is a different
distribution (nicknames, typos, non-Western names) and will likely score
lower. Prefer :class:`~veil.backends.known_entities.KnownEntitiesBackend`
whenever your application already has the identity, and treat this backend
as a recall-booster for names you don't already know about, not a
guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass

from veil.types import Entity, EntityType, Span

_LABEL_MAP = {
    "PERSON": EntityType.PERSON,
    "PER": EntityType.PERSON,
    "ORG": EntityType.ORG,
    "GPE": EntityType.LOCATION,
    "LOC": EntityType.LOCATION,
    "FAC": EntityType.LOCATION,
}


@dataclass
class SpacyBackend:
    """Wraps a loaded spaCy pipeline as a :class:`veil.backends.base.NameBackend`."""

    model: str = "en_core_web_sm"
    name: str = "spacy"

    def __post_init__(self) -> None:
        try:
            import spacy  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise ImportError(
                "SpacyBackend requires the 'spacy' extra: pip install \"veil-pii[spacy]\""
            ) from exc
        try:
            self._nlp = spacy.load(self.model)
        except OSError as exc:  # pragma: no cover - requires a model download
            raise OSError(
                f"spaCy model {self.model!r} is not installed. "
                f"Run: python -m spacy download {self.model}"
            ) from exc

    def find(self, text: str) -> list[Entity]:
        doc = self._nlp(text)
        out: list[Entity] = []
        for ent in doc.ents:
            etype = _LABEL_MAP.get(ent.label_)
            if etype is None:
                continue
            out.append(
                Entity(
                    type=etype,
                    value=ent.text,
                    span=Span(ent.start_char, ent.end_char),
                    detector=self.name,
                    confidence=0.7,  # unmeasured; see module docstring
                )
            )
        return out
