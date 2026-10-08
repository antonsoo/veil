"""Payment card number detector.

A card number is 13 to 19 digits that pass the Luhn checksum. One digit run
in ten passes it by chance, and logs, timestamps, block ids and business
registration numbers are full of digit runs, so the checksum is not enough.
A candidate needs a second piece of evidence:

- its leading digits and its length belong to a card network (the IIN
  ranges below), or
- it is written the way a card is printed: groups of four, or 4-6-5 and
  4-6-4, with one separator used throughout.

It must also stand alone. Digits glued to a word, a path, a version or a
decimal point (``blk_-6952295868487656571``, ``v0.0.0-20180228061459-e0a3``,
``0.4111111111111111``) are part of something else, and so is a run of
separate numbers that only adds up to a card's length
(``081109 204453 34`` is a date, a time and a process id).

A run of digits inside an IBAN can pass Luhn too; a candidate overlapping a
span :class:`~veil.detectors.iban.IbanDetector` recognizes is dropped.
"""

from __future__ import annotations

import re

from veil._spans import SpanIndex
from veil.detectors.iban import IbanDetector
from veil.types import Entity, EntityType, Span

_CANDIDATE_RE = re.compile(
    r"(?<![\w.+\-/])"
    r"(?:"
    r"(?P<solid>\d{13,19})"
    r"|"
    r"(?<!\d[ -])(?P<grouped>"
    r"\d{4}(?P<sep>[ -])\d{4}(?P=sep)\d{4}(?:(?P=sep)\d{4})?(?:(?P=sep)\d{1,4})?"
    r"|\d{4}(?P<sep2>[ -])\d{6}(?P=sep2)\d{4,5}"
    r")(?![ -]\d)"
    r")"
    r"(?!\w)(?![.\-/]\w)"
)

# A number labelled as something else that also carries a Luhn check digit:
# French SIRET and SIREN business numbers, device IMEIs, SIM card ICCIDs.
_OTHER_LUHN_LABEL_RE = re.compile(r"\b(siret|siren|imei|iccid)\b", re.IGNORECASE)
_LABEL_WINDOW = 32


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


# (leading digits, valid lengths) for the networks listed as active in the
# IIN table of Wikipedia's "Payment card number" (revision 1373981599 of
# 9 September 2026). UATP, any 15 digits starting with 1, is left out: it is
# an airline billing account, and in a log it is every other fifteen-digit
# id. Written in groups, one is still found.
_ISSUER_RANGES: list[tuple[re.Pattern[str], set[int]]] = [
    (re.compile(r"^4"), {13, 16, 19}),  # Visa
    (re.compile(r"^(5[1-5]|2(2[2-9]\d|[3-6]\d\d|7[01]\d|720))"), {16}),  # Mastercard
    (re.compile(r"^3[47]"), {15}),  # American Express
    (re.compile(r"^(6011|65|64[4-9])"), set(range(16, 20))),  # Discover
    (re.compile(r"^(30|36|38|39)"), set(range(14, 20))),  # Diners Club International
    (re.compile(r"^35(2[89]|[3-8]\d)"), set(range(16, 20))),  # JCB
    (re.compile(r"^62"), set(range(16, 20))),  # China UnionPay
    (re.compile(r"^(5018|5020|5038|5893|6304|6759|6761|6762|6763)"), set(range(13, 20))),  # Maestro
    (re.compile(r"^(50|56|58|6[0-3])"), {16, 18, 19}),  # GPN, Verve, Dankort, UkrCart
    (re.compile(r"^(60|65|81|82|508)"), {16}),  # RuPay
    (re.compile(r"^220[0-4]"), set(range(16, 20))),  # Mir
    (re.compile(r"^2205"), {16}),  # BORICA
    (re.compile(r"^636"), set(range(16, 20))),  # InterPayment
    (re.compile(r"^63[7-9]"), {16}),  # InstaPayment
    (re.compile(r"^(9792|8600|5614|9860)"), {16}),  # Troy, Uzcard, HUMO
    (re.compile(r"^(9704|1946)"), {16, 18, 19}),  # Napas, GPN (BNI)
    (re.compile(r"^(31|960046)"), {19}),  # China T-Union, WEX
]


def known_issuer(digits: str) -> bool:
    return any(rx.match(digits) and len(digits) in lengths for rx, lengths in _ISSUER_RANGES)


class CardDetector:
    name = "card"

    def __init__(self) -> None:
        self._iban_detector = IbanDetector()

    def find(self, text: str) -> list[Entity]:
        ibans = SpanIndex(e.span for e in self._iban_detector.find(text))
        out: list[Entity] = []
        for m in _CANDIDATE_RE.finditer(text):
            raw = m.group(0)
            digits = re.sub(r"[ -]", "", raw)
            if not (13 <= len(digits) <= 19) or digits[0] == "0" or not luhn_ok(digits):
                continue
            issuer = known_issuer(digits)
            # Unformatted digits need the network's range and length to count.
            if m.group("solid") and not issuer:
                continue
            if _OTHER_LUHN_LABEL_RE.search(text, max(0, m.start() - _LABEL_WINDOW), m.start()):
                continue
            span = Span(m.start(), m.end())
            if ibans.overlaps(span):
                continue
            out.append(
                Entity(
                    type=EntityType.CARD,
                    value=raw,
                    span=span,
                    detector=self.name,
                    confidence=0.98 if issuer else 0.7,
                )
            )
        return out
