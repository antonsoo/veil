"""Phone number detector.

Covers three shapes:

- E.164: ``+`` followed by 8-15 digits, first digit 1-9.
- NANP (US/Canada): ``(area) exchange-line``, ``area-exchange-line``, or
  ``area.exchange.line``, optionally prefixed with a ``1``.
- Generic international: groups of digits separated by spaces, dots, or
  dashes, 7-15 digits total, optionally in parens for the first group.

Structural validation only (digit counts, NANP area/exchange codes cannot
start with 0 or 1) — there is no offline way to confirm a number is
*assigned*, only that it is *well-formed*.

**Deliberate recall/precision trade-off:** an unformatted, unprefixed
digit run (no ``+``, no spaces/dashes/dots/parens — e.g. a bare
``"4111111111111111"``) is *not* treated as a phone candidate at all,
even though some real phone numbers are written that way. Without a
separator or a leading ``+``, there is no way to tell a phone number
apart from a card number, account number, or IBAN digit group, and in
practice those are far more common in running text than an unformatted
phone number. Evaluated on this project's synthetic corpus
(``benchmarks/``), lifting this restriction measurably drops phone
precision by flagging card-number substrings as phone numbers.

A dash-separated ``XXX-XX-XXXX`` group is structurally identical to both
a generic international phone number and a US SSN, and a dot-separated
group is structurally identical to an IPv4 address (including a *partial*
IPv4 octet run). Rather than guess, this detector defers to
:class:`~veil.detectors.ssn.SsnDetector` and
:class:`~veil.detectors.ip.IpDetector`: any phone candidate that overlaps
a span either of them recognizes is dropped.
"""

from __future__ import annotations

import re

from veil.detectors.ip import IpDetector
from veil.detectors.ssn import SsnDetector
from veil.types import Entity, EntityType, Span

_CANDIDATE_RE = re.compile(
    r"(?<![\w])"
    r"(?:"
    r"\+\d{8,15}"  # contiguous, but only with an explicit country-code "+"
    r"|"
    r"(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{2,4}(?:[\s.-]\d{2,4}){1,4}"
    r")"
    r"(?![\w])"
)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


_NANP_RE = re.compile(
    r"^\+?1?[\s.-]?\(?(?P<area>[2-9]\d{2})\)?[\s.-]?(?P<exch>[2-9]\d{2})[\s.-]?(?P<line>\d{4})$"
)


def _is_nanp(candidate: str) -> bool:
    return bool(_NANP_RE.match(candidate.strip()))


def _is_e164(candidate: str) -> bool:
    c = candidate.strip()
    if not c.startswith("+"):
        return False
    digits = _digits(c)
    return 8 <= len(digits) <= 15 and digits[0] != "0"


def _is_plausible_international(candidate: str) -> bool:
    digits = _digits(candidate)
    return 7 <= len(digits) <= 15


class PhoneDetector:
    name = "phone"

    def __init__(self) -> None:
        self._ip_detector = IpDetector()
        self._ssn_detector = SsnDetector()

    def find(self, text: str) -> list[Entity]:
        conflicting_spans = [e.span for e in self._ip_detector.find(text)] + [
            e.span for e in self._ssn_detector.find(text)
        ]
        out: list[Entity] = []
        for m in _CANDIDATE_RE.finditer(text):
            candidate = m.group(0)
            digits = _digits(candidate)
            if len(digits) < 7:
                continue
            span = Span(m.start(), m.end())
            if any(span.overlaps(c) for c in conflicting_spans):
                continue
            if not (
                _is_e164(candidate) or _is_nanp(candidate) or _is_plausible_international(candidate)
            ):
                continue
            out.append(
                Entity(
                    type=EntityType.PHONE,
                    value=candidate,
                    span=span,
                    detector=self.name,
                    confidence=0.95 if _is_e164(candidate) or _is_nanp(candidate) else 0.6,
                )
            )
        return out
