"""Payment card number detector.

Validates candidates with the Luhn checksum and cross-checks the leading
digits (IIN / issuer identification number) and total length against the
publicly documented ranges for the major networks. A number that passes
Luhn but matches no known issuer range is still reported, at lower
confidence, since new/private ranges exist that we don't enumerate.

A run of 13-19 digits embedded in a longer digit string (e.g. the BBAN
portion of an IBAN, right after the 2-letter country code) can coincidentally
pass Luhn about 1 time in 10. To cut that down, a candidate overlapping a
span :class:`~veil.detectors.iban.IbanDetector` recognizes is dropped.
"""

from __future__ import annotations

import re

from veil.detectors.iban import IbanDetector
from veil.types import Entity, EntityType, Span

_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# (prefix-matcher, valid lengths)
_ISSUER_RANGES: list[tuple[re.Pattern[str], set[int]]] = [
    (re.compile(r"^4"), {13, 16, 19}),  # Visa
    (re.compile(r"^(5[1-5]|2(2[2-9]\d|[3-6]\d\d|7[01]\d|720))"), {16}),  # Mastercard
    (re.compile(r"^3[47]"), {15}),  # American Express
    (re.compile(r"^(6011|65|64[4-9])"), {16, 19}),  # Discover
    (re.compile(r"^(30[0-5]|36|38|39)"), {14}),  # Diners Club
    (re.compile(r"^35(2[89]|[3-8]\d)"), {16}),  # JCB
]


def known_issuer(digits: str) -> bool:
    return any(rx.match(digits) and len(digits) in lengths for rx, lengths in _ISSUER_RANGES)


class CardDetector:
    name = "card"

    def __init__(self) -> None:
        self._iban_detector = IbanDetector()

    def find(self, text: str) -> list[Entity]:
        iban_spans = [e.span for e in self._iban_detector.find(text)]
        out: list[Entity] = []
        for m in _CANDIDATE_RE.finditer(text):
            # The candidate group is "digit + optional separator", so a
            # trailing space/dash before non-digit text (e.g. "...1111 for
            # the renewal") gets greedily absorbed into the last repetition.
            # Trim it back off before it's treated as part of the number.
            raw = m.group(0).rstrip(" -")
            digits = re.sub(r"[ -]", "", raw)
            if not (13 <= len(digits) <= 19) or not luhn_ok(digits):
                continue
            span = Span(m.start(), m.start() + len(raw))
            if any(span.overlaps(c) for c in iban_spans):
                continue
            out.append(
                Entity(
                    type=EntityType.CARD,
                    value=raw,
                    span=span,
                    detector=self.name,
                    confidence=0.98 if known_issuer(digits) else 0.7,
                )
            )
        return out
