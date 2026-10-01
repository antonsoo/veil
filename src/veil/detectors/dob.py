"""Date-of-birth detector.

A bare date (``03/14/1990``) is ambiguous — it could be an appointment, an
invoice date, anything. We only flag a date when it is near an explicit
birth-context keyword (``DOB``, ``date of birth``, ``born on``, ``birthdate``),
which is the same heuristic a human skimming the text would use.
"""

from __future__ import annotations

import re
from bisect import bisect_left

from veil.types import Entity, EntityType, Span

_CONTEXT_RE = re.compile(r"\b(dob|date of birth|birth ?date|born on|born)\b", re.IGNORECASE)

_DATE_RE = re.compile(
    r"\b("
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"  # 03/14/1990, 14-03-1990
    r"|\d{4}-\d{2}-\d{2}"  # 1990-03-14 (ISO)
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)

_CONTEXT_WINDOW = 30


def _any_within(positions: list[int], centre: int, distance: int) -> bool:
    """Is any of the sorted ``positions`` at most ``distance`` from ``centre``?"""
    i = bisect_left(positions, centre - distance)
    return i < len(positions) and positions[i] <= centre + distance


class DobDetector:
    name = "dob"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        # Keyword matches come in text order and don't overlap, so both lists are sorted.
        starts: list[int] = []
        ends: list[int] = []
        for c in _CONTEXT_RE.finditer(text):
            starts.append(c.start())
            ends.append(c.end())
        if not starts:
            return out
        for m in _DATE_RE.finditer(text):
            if not (
                _any_within(ends, m.start(), _CONTEXT_WINDOW)
                or _any_within(starts, m.end(), _CONTEXT_WINDOW)
            ):
                continue
            out.append(
                Entity(
                    type=EntityType.DOB,
                    value=m.group(0),
                    span=Span(m.start(), m.end()),
                    detector=self.name,
                    confidence=0.85,
                )
            )
        return out
