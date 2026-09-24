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
"""

from __future__ import annotations

import re

from veil.types import Entity, EntityType, Span

_CANDIDATE_RE = re.compile(
    r"(?<![\w])"
    r"(?:"
    r"\+?\d{8,15}"  # contiguous, e.g. +12025551234
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

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _CANDIDATE_RE.finditer(text):
            candidate = m.group(0)
            digits = _digits(candidate)
            if len(digits) < 7:
                continue
            if not (
                _is_e164(candidate) or _is_nanp(candidate) or _is_plausible_international(candidate)
            ):
                continue
            out.append(
                Entity(
                    type=EntityType.PHONE,
                    value=candidate,
                    span=Span(m.start(), m.end()),
                    detector=self.name,
                    confidence=0.95 if _is_e164(candidate) or _is_nanp(candidate) else 0.6,
                )
            )
        return out
