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
from veil.types import Entity, Span
from veil.vault import Vault


@dataclass(frozen=True, slots=True)
class LeakFinding:
    kind: str  # "leaked_original" or "new_pii"
    entity: Entity


def find_leaked_originals(text: str, vault: Vault) -> list[LeakFinding]:
    findings: list[LeakFinding] = []
    for mapping in vault.mappings():
        if not mapping.original:
            continue
        start = 0
        while True:
            idx = text.find(mapping.original, start)
            if idx == -1:
                break
            findings.append(
                LeakFinding(
                    kind="leaked_original",
                    entity=Entity(
                        type=mapping.type,
                        value=mapping.original,
                        span=Span(idx, idx + len(mapping.original)),
                        detector="vault",
                        confidence=1.0,
                    ),
                )
            )
            start = idx + len(mapping.original)
    findings.sort(key=lambda f: f.entity.span.start)
    return findings


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
