"""Phone number detector.

Covers exactly two shapes, both structurally strict on purpose:

- NANP (US/Canada): 10 digits as ``area-exchange-line``, ``(area)
  exchange-line``, or ``area.exchange.line``, optionally prefixed with a
  ``1``. Area and exchange codes cannot start with 0 or 1 (real NANP
  numbers never do).
- International: an explicit leading ``+``, a country calling code the ITU
  has assigned, and a national number of a length that country uses, with
  the digits grouped however the writer liked (``+33 1 23 45 67 89``,
  ``+49 30 12345678``, ``+81 3-1234-5678``, ``+44 (0)20 7946 0958``). The
  codes and lengths are in :mod:`veil.detectors._calling_codes`.

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

from veil._spans import DisjointSpans, SpanIndex
from veil.detectors._calling_codes import split_international
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


# "+", then groups of digits. Between two groups: at most one of . - /, with
# an optional space on either side, so "+49 30 / 123456" and "+1 (212)
# 555-1234" hold together and a line break never does.
_GAP = r"(?:[ \u00a0\u202f]?[.\-/]?[ \u00a0\u202f]?)"
_GROUP = r"(?:\(\d{1,5}\)|\d{1,14})"
_INTERNATIONAL_RE = re.compile(rf"(?<![\w+])\+{_GROUP}(?:{_GAP}{_GROUP}){{0,8}}")
_GROUP_RE = re.compile(_GROUP)
# "+32.035815963" is a signed decimal (Go prints its monotonic clock that
# way), and a calendar date ends whatever number came before it.
_SIGNED_DECIMAL_RE = re.compile(r"\+\d+\.\d+")
_ISO_DATE_RE = re.compile(r"(?<!\d)(?:19|20)\d\d-[01]\d-[0-3]\d(?!\d)")
_EXTENSION_RE = re.compile(r"[xX]\d")


def _is_valid_international(digits: str) -> bool:
    parts = split_international(digits)
    if parts is None:
        return False
    code, national = parts
    if code == "1":  # North America: ten digits, area and exchange from 2 up
        return len(national) == 10 and national[0] not in "01" and national[3] not in "01"
    return True


def _international_end(candidate: str) -> int | None:
    """Length of the longest run of leading groups that makes a valid number.

    Digits that follow a number ("+1 212 555 0134 2026") are tried first as
    part of it and then dropped group by group. A "(0)" after the calling
    code is the trunk prefix some countries print for domestic callers; it
    is not part of the number.
    """
    if _SIGNED_DECIMAL_RE.fullmatch(candidate):
        return None
    date = _ISO_DATE_RE.search(candidate)
    if date is not None:
        candidate = candidate[: date.start()]
    groups = list(_GROUP_RE.finditer(candidate))
    for count in range(len(groups), 0, -1):
        digits = "".join(
            _digits(g.group(0))
            for i, g in enumerate(groups[:count])
            if not (i == 1 and g.group(0) == "(0)")
        )
        if 8 <= len(digits) <= 15 and _is_valid_international(digits):
            end = groups[count - 1].end()
            if end == len(candidate) or not candidate[end : end + 1].isdigit():
                return end
    return None


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
        ip_spans = [e.span for e in self._ip_detector.find(text)]
        addresses = SpanIndex(ip_spans)
        conflicting = SpanIndex(ip_spans + [e.span for e in self._ssn_detector.find(text)])
        out: list[Entity] = []
        international = DisjointSpans()
        for m in _INTERNATIONAL_RE.finditer(text):
            end = _international_end(m.group(0))
            if end is None:
                continue
            span = Span(m.start(), m.start() + end)
            after = text[span.end : span.end + 2]
            if (after[:1].isalnum() or after[:1] == "_") and not _EXTENSION_RE.match(after):
                continue
            # A calling code and a valid length outweigh the three-two-four
            # shape of a US SSN somewhere inside ("+33 142 78 2350").
            if addresses.overlaps(span) or _has_blocking_context(text, m.start()):
                continue
            international.add(span)
            out.append(
                Entity(
                    type=EntityType.PHONE,
                    value=text[span.start : span.end],
                    span=span,
                    detector=self.name,
                    confidence=0.95,
                )
            )
        for m in _CANDIDATE_RE.finditer(text):
            candidate = m.group(0)
            digits = _digits(candidate)
            if len(digits) < 7:
                continue
            span = Span(m.start(), m.end())
            if conflicting.overlaps(span) or international.overlaps(span):
                continue
            # A "+" form was judged above; only the national shape is left.
            if candidate.startswith("+") or not _is_nanp(candidate):
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
        out.sort(key=lambda e: e.span.start)
        return out
