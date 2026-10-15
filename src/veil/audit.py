"""Leak audit: catch original PII that reached outgoing text, and new PII
the model introduced on its own.

Two independent checks, both useful before text leaves your network the
*second* time (e.g. a restored reply that's about to be logged, emailed,
or shown to a different user than the one it's about):

1. :func:`find_leaked_originals` — did any value the vault knows about
   (i.e. was masked out of the prompt) show up verbatim in ``text``? This
   catches cases where the model was told the original value some other
   way (e.g. it appeared in a tool result you forgot to mask) or where a
   restore step ran against the wrong vault.
2. :func:`find_new_pii` — does ``text`` contain PII-shaped values that
   *aren't* in the vault at all? A model can hallucinate a plausible
   email address, invent an SSN-shaped number, or echo PII a user typed
   in a later turn that was never routed through :class:`~veil.masker.Masker`.
   This runs the same detectors used for masking, then filters out
   anything wholly inside an exact occurrence of an original (already covered
   by check 1) or a surrogate (expected, pre-restore). Partial overlaps and
   values crossing two separate known literals remain new candidates.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from veil._spans import SpanIndex
from veil.detectors import default_detectors
from veil.detectors.base import Detector
from veil.types import Entity, Mapping, Span
from veil.vault import Vault


@dataclass(frozen=True, slots=True)
class LeakFinding:
    kind: str  # "leaked_original" or "new_pii"
    entity: Entity


# Keep candidate slices bounded even when a vault holds thousands of long,
# differently sized URLs or documents. A prefix is only a candidate filter;
# full originals, never their prefixes, establish a leak.
_PREFIX_LENGTH = 32
_Entries = list[tuple[int, Mapping]]
_ByValue = dict[str, _Entries]
_Candidates = dict[str, list[tuple[int, _ByValue]]]


def _values_index(
    vault: Vault, *, surrogates: bool = False
) -> tuple[_Candidates, dict[str, list[int]]]:
    """Exact known literals grouped by bounded prefix, then complete length and value."""
    key = "audit_surrogates" if surrogates else "originals"
    index = vault._derived.get(key)
    if index is None:
        by_value: _ByValue = {}
        for order, mapping in enumerate(vault.mappings()):
            value = mapping.surrogate if surrogates else mapping.original
            if value:
                by_value.setdefault(value, []).append((order, mapping))
        grouped: dict[str, dict[int, _ByValue]] = {}
        lengths: dict[str, set[int]] = {}
        for value, entries in by_value.items():
            prefix = value[:_PREFIX_LENGTH]
            grouped.setdefault(prefix, {}).setdefault(len(value), {})[value] = entries
            lengths.setdefault(value[0], set()).add(len(prefix))
        index = vault._derived[key] = (
            {prefix: list(by_length.items()) for prefix, by_length in grouped.items()},
            {first: sorted(found) for first, found in lengths.items()},
        )
    return index


def _value_matches(
    text: str, vault: Vault, *, surrogates: bool = False
) -> Iterator[tuple[int, str, _Entries]]:
    """Every exact literal occurrence, including overlaps of the same value."""
    # At most 32 candidate lengths per starting character. Shared prefixes can
    # require several full comparisons; never treat a prefix as proof of a leak.
    candidates, lengths_by_first = _values_index(vault, surrogates=surrogates)
    if not candidates:
        return
    for start, ch in enumerate(text):
        for length in lengths_by_first.get(ch, ()):
            if start + length > len(text):
                break
            for full_length, by_value in candidates.get(text[start : start + length], ()):
                if len(by_value) == 1:
                    value, entries = next(iter(by_value.items()))
                    if not text.startswith(value, start):
                        continue
                else:
                    # Many equal-length originals can share a URL host or PEM
                    # header. One full hash lookup avoids comparing each one.
                    # This longer slice is needed only after its prefix matches.
                    value = text[start : start + full_length]
                    entries = by_value.get(value, [])
                    if not entries:
                        continue
                yield start, value, entries


def find_leaked_originals(text: str, vault: Vault) -> list[LeakFinding]:
    found: list[tuple[int, int, Mapping]] = []
    free_from: dict[str, int] = {}  # occurrences of one value are counted without overlap
    for start, value, entries in _value_matches(text, vault):
        if start < free_from.get(value, 0):
            continue
        free_from[value] = start + len(value)
        found.extend((start, order, mapping) for order, mapping in entries)
    found.sort(key=lambda item: item[:2])
    return [
        LeakFinding(
            kind="leaked_original",
            entity=Entity(
                type=mapping.type,
                value=mapping.original,
                span=Span(start, start + len(mapping.original)),
                detector="vault",
                confidence=1.0,
            ),
        )
        for start, _, mapping in found
    ]


def find_new_pii(
    text: str, vault: Vault, detectors: list[Detector] | None = None
) -> list[LeakFinding]:
    """New detector findings outside exact known literals. ``[]`` selects no detectors.

    An embedded email or address is already known when a whole enclosing URL
    belongs to the vault. Merely overlapping one known literal, or crossing
    adjacent literals, does not establish that the complete candidate is known.
    """
    selected = default_detectors() if detectors is None else detectors
    if not selected:
        return []
    known_originals = set(vault.originals())
    known_surrogates = set(vault.surrogates())
    candidates = [
        entity
        for detector in selected
        for entity in detector.find(text)
        if entity.value not in known_originals and entity.value not in known_surrogates
    ]
    if not candidates:
        return []
    # Coverage needs every literal occurrence. The reporting policy's
    # nonoverlapping original matches would miss a suffix of "ababa" when
    # "aba" is known: its second, overlapping occurrence still owns that text.
    protected = SpanIndex(
        Span(start, start + len(value))
        for surrogates in (False, True)
        for start, value, _ in _value_matches(text, vault, surrogates=surrogates)
    )
    findings = [
        LeakFinding(kind="new_pii", entity=entity)
        for entity in candidates
        if not protected.contains(entity.span)
    ]
    findings.sort(key=lambda f: f.entity.span.start)
    return findings


def audit(text: str, vault: Vault, detectors: list[Detector] | None = None) -> list[LeakFinding]:
    """Run both checks in text order. ``detectors`` selects only the new-PII check."""
    findings = find_leaked_originals(text, vault) + find_new_pii(text, vault, detectors)
    findings.sort(key=lambda f: f.entity.span.start)
    return findings
