"""The masking pipeline: text -> (masked text, vault).

Ties together detectors, name backends, a surrogate generator, and a vault.
Detector results are pooled, overlaps resolved (higher confidence wins,
ties broken by longer span, then earliest detector), and replaced in
reading order, so the first value of a type in a text is numbered 1.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from veil._spans import DisjointSpans
from veil.backends.base import NameBackend
from veil.detectors import default_detectors
from veil.detectors.base import Detector
from veil.restore import restore_exact, restore_tolerant
from veil.surrogates import PlaceholderSurrogates, SurrogateGenerator
from veil.types import Entity
from veil.vault import Vault, VaultError


def _spelling(text: str) -> str:
    # Conservative reservation for the case/whitespace rewrites accepted by
    # tolerant restoration. The final check uses the actual restorers as well.
    return " ".join(text.split()).casefold()


@dataclass
class _MaskingBatch:
    sources: dict[str, list[str]] = field(default_factory=dict)
    pairs: list[tuple[str, str]] = field(default_factory=list)
    used: set[str] = field(default_factory=set)
    originals: set[str] = field(default_factory=set)

    def reserve(self, text: str) -> None:
        normalized = _spelling(text)
        # Index once per source, not once per candidate surrogate. The usual
        # placeholder delimiter is absent from most texts in a large batch.
        # Add later nested inputs too: the final check must see every source.
        for char in set(normalized):
            self.sources.setdefault(char, []).append(normalized)

    def available(self, surrogate: str) -> bool:
        normalized = _spelling(surrogate)
        return (
            bool(normalized)
            and normalized not in self.originals
            and not any(normalized in source for source in self.sources.get(normalized[0], ()))
        )


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
    """Reuse a vault so repeated values keep the same surrogate. Use
    :meth:`mask_many` for related raw texts: reservations cover the whole
    batch, including literal examples in other messages. Source texts are
    not retained between batches; include earlier raw texts when adding turns.
    """

    detectors: list[Detector] = field(default_factory=default_detectors)
    name_backends: list[NameBackend] = field(default_factory=list)
    surrogate_generator: SurrogateGenerator = field(default_factory=PlaceholderSurrogates)
    vault: Vault = field(default_factory=Vault)
    _batch: _MaskingBatch | None = field(default=None, init=False, repr=False, compare=False)

    @contextmanager
    def _masking_batch(self) -> Iterator[_MaskingBatch]:
        """Internal request boundary. No prepared output may escape before exit.

        Wrappers nest their ordinary mask calls here, before invoking the SDK.
        A batch retains source text only until preparation finishes. Maskers
        and their vaults are for sequential use, not shared concurrent writes.
        """
        if self._batch is not None:
            yield self._batch
            return
        batch = _MaskingBatch(originals={_spelling(s) for s in self.vault.originals()})
        with self.vault._transaction():
            self._batch = batch
            try:
                yield batch
                if any(not batch.available(s) for s in batch.used):
                    raise VaultError(
                        "a surrogate conflicts with another input in this request; "
                        "remask the complete input with a fresh vault using mask_many"
                    )
                for source, masked in batch.pairs:
                    if (
                        restore_exact(masked, self.vault) != source
                        or restore_tolerant(masked, self.vault) != source
                    ):
                        raise VaultError(
                            "source text would change during surrogate restoration; "
                            "use a fresh vault to remask the complete input"
                        )
            finally:
                self._batch = None

    def mask_many(self, texts: Sequence[str]) -> list[str]:
        """Mask related raw texts together, reserving literals across all of them.

        Either every result restores to its source or VaultError is raised and
        this batch's vault changes are undone. No earlier source texts are kept
        between calls; submit the complete raw conversation when adding turns.
        """
        if isinstance(texts, str):
            raise TypeError("mask_many expects a sequence of strings, not one string")
        with self._masking_batch() as batch:
            for text in texts:
                batch.reserve(text)
            return [self._mask(text, batch) for text in texts]

    def find_entities(self, text: str) -> list[Entity]:
        found: list[Entity] = []
        for detector in self.detectors:
            found.extend(detector.find(text))
        for backend in self.name_backends:
            found.extend(backend.find(text))
        return _resolve_overlaps(found)

    def mask(self, text: str) -> str:
        """Mask one raw text; reject ambiguous restoration without changing the vault."""
        return self.mask_many([text])[0]

    def _mask(self, text: str, batch: _MaskingBatch) -> str:
        parts: list[str] = []
        pos = 0
        for entity in self.find_entities(text):
            batch.originals.add(_spelling(entity.value))
            surrogate = self.vault.get_or_create(
                entity.type,
                entity.value,
                self.surrogate_generator,
                entity.detector,
                available=batch.available,
            )
            batch.used.add(surrogate)
            parts.append(text[pos : entity.span.start])
            parts.append(surrogate)
            pos = entity.span.end
        parts.append(text[pos:])
        masked = "".join(parts)
        batch.pairs.append((text, masked))
        return masked

    def restore(self, text: str, *, tolerant: bool = True) -> str:
        """Restore surrogates in ``text`` using this masker's vault.

        ``tolerant=True`` (the default) also catches case changes and
        possessives a model commonly introduces; pass ``False`` for
        byte-exact matching only. For a token stream, use
        :class:`veil.restore.Restorer` directly instead.
        """
        return restore_tolerant(text, self.vault) if tolerant else restore_exact(text, self.vault)
