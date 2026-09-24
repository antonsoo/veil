"""Date-of-birth detector.

A bare date (``03/14/1990``) is ambiguous — it could be an appointment, an
invoice date, anything. We only flag a date when it is near an explicit
birth-context keyword (``DOB``, ``date of birth``, ``born on``, ``birthdate``),
which is the same heuristic a human skimming the text would use.
"""

from __future__ import annotations

import re

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


class DobDetector:
    name = "dob"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        context_spans = [Span(m.start(), m.end()) for m in _CONTEXT_RE.finditer(text)]
        if not context_spans:
            return out
        for m in _DATE_RE.finditer(text):
            near = any(
                abs(m.start() - c.end) <= _CONTEXT_WINDOW
                or abs(c.start - m.end()) <= _CONTEXT_WINDOW
                for c in context_spans
            )
            if not near:
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
