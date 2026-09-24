"""Payment card number detector.

Validates candidates with the Luhn checksum and cross-checks the leading
digits (IIN / issuer identification number) and total length against the
publicly documented ranges for the major networks. A number that passes
Luhn but matches no known issuer range is still reported, at lower
confidence, since new/private ranges exist that we don't enumerate.
"""

from __future__ import annotations

import re

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

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _CANDIDATE_RE.finditer(text):
            raw = m.group(0)
            digits = re.sub(r"[ -]", "", raw)
            if not (13 <= len(digits) <= 19) or not luhn_ok(digits):
                continue
            out.append(
                Entity(
                    type=EntityType.CARD,
                    value=raw,
                    span=Span(m.start(), m.end()),
                    detector=self.name,
                    confidence=0.98 if known_issuer(digits) else 0.7,
                )
            )
        return out
