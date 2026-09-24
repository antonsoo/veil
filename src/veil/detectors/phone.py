"""Phone number detector.

Covers exactly two shapes, both structurally strict on purpose:

- NANP (US/Canada): 10 digits as ``area-exchange-line``, ``(area)
  exchange-line``, or ``area.exchange.line``, optionally prefixed with a
  ``1``. Area and exchange codes cannot start with 0 or 1 (real NANP
  numbers never do).
- E.164 / international: an explicit leading ``+`` followed by 8-15
  digits, first digit 1-9.

There is no third "generic, separator-only, no country code" bucket.
Earlier versions had one (any 7-15 digit run split by spaces/dots/dashes),
and it over-masked: an ISO date (``2026-09-21``), an order number
(``#4417-2291``), or any other dash/dot-separated digit group that isn't
actually NANP- or E.164-shaped would get flagged. Losing that bucket is a
real recall trade-off — some real phone numbers are written without a
country code in a non-NANP format (e.g. a UK number as ``020 7946
0958``) and this detector will miss them — but per-1,000-word false
positives on ordinary business text (``benchmarks/``) matter more here
than that recall gap.

**Context guard.** Even a structurally NANP-shaped 10-digit run can be
something else — an order number, invoice ID, or ticket number that
happens to land on a valid-looking area/exchange code. A candidate
immediately preceded by ``#``, "order", "invoice", "inv-", "ticket", or
"zip" (case-insensitive, within a short window) is dropped.

Structural validation only — there is no offline way to confirm a number
is *assigned*, only that it is *well-formed*.

A dash-separated ``XXX-XX-XXXX`` group is structurally identical to a US
SSN, and a dot-separated group is structurally identical to an IPv4
address (including a *partial* IPv4 octet run). Rather than guess, this
detector defers to :class:`~veil.detectors.ssn.SsnDetector` and
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


# Order/invoice/ticket/ZIP context that should suppress an otherwise
# NANP-shaped match. "#" alone (a leading number sign right before the
# candidate) is included since it's the single most common order/ticket
# marker ("Order #4417-2291", "Ticket #202-555-0199").
_BLOCKING_CONTEXT_RE = re.compile(r"(#\s*$|\b(order|invoice|inv-|ticket|zip)\b)", re.IGNORECASE)
_CONTEXT_WINDOW = 15


def _has_blocking_context(text: str, start: int) -> bool:
    window = text[max(0, start - _CONTEXT_WINDOW) : start]
    return bool(_BLOCKING_CONTEXT_RE.search(window))


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
            is_e164 = _is_e164(candidate)
            is_nanp = _is_nanp(candidate)
            if not (is_e164 or is_nanp):
                continue
            if _has_blocking_context(text, m.start()):
                continue
            out.append(
                Entity(
                    type=EntityType.PHONE,
                    value=candidate,
                    span=span,
                    detector=self.name,
                    confidence=0.95,
                )
            )
        return out
