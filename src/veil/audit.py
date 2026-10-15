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
   anything that matches a known surrogate's original (already covered by
   check 1) or a known surrogate string itself (expected, pre-restore).
"""

from __future__ import annotations

from dataclasses import dataclass

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
# startswith below still verifies the complete original, without copying it.
_PREFIX_LENGTH = 32
_Entries = list[tuple[int, Mapping]]
_Candidates = dict[str, list[tuple[str, _Entries]]]


def _originals_index(vault: Vault) -> tuple[_Candidates, dict[str, list[int]]]:
    """Exact originals grouped by a bounded prefix, plus prefix lengths by first character."""
    index = vault._derived.get("originals")
    if index is None:
        by_value: dict[str, _Entries] = {}
        for order, mapping in enumerate(vault.mappings()):
            if mapping.original:
                by_value.setdefault(mapping.original, []).append((order, mapping))
        candidates: _Candidates = {}
        lengths: dict[str, set[int]] = {}
        for value, entries in by_value.items():
            prefix = value[:_PREFIX_LENGTH]
            candidates.setdefault(prefix, []).append((value, entries))
            lengths.setdefault(value[0], set()).add(len(prefix))
        index = vault._derived["originals"] = (
            candidates,
            {first: sorted(found) for first, found in lengths.items()},
        )
    return index


def find_leaked_originals(text: str, vault: Vault) -> list[LeakFinding]:
    # At most 32 candidate lengths per starting character. Shared prefixes can
    # require several full comparisons; never treat a prefix as proof of a leak.
    candidates, lengths_by_first = _originals_index(vault)
    found: list[tuple[int, int, Mapping]] = []
    free_from: dict[str, int] = {}  # occurrences of one value are counted without overlap
    for start, ch in enumerate(text):
        for length in lengths_by_first.get(ch, ()):
            for value, entries in candidates.get(text[start : start + length], ()):
                if start < free_from.get(value, 0) or not text.startswith(value, start):
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
    known_originals = set(vault.originals())
    known_surrogates = set(vault.surrogates())
    findings: list[LeakFinding] = []
    for detector in detectors or default_detectors():
        for entity in detector.find(text):
            if entity.value in known_originals or entity.value in known_surrogates:
                continue
            findings.append(LeakFinding(kind="new_pii", entity=entity))
    findings.sort(key=lambda f: f.entity.span.start)
    return findings


def audit(text: str, vault: Vault, detectors: list[Detector] | None = None) -> list[LeakFinding]:
    """Run both checks and return combined findings, in text order."""
    findings = find_leaked_originals(text, vault) + find_new_pii(text, vault, detectors)
    findings.sort(key=lambda f: f.entity.span.start)
    return findings
