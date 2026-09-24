"""US Social Security Number detector.

Matches ``AAA-GG-SSSS`` (with `-`, ` `, or no separator) and excludes area,
group, and serial values the SSA has documented as never issued:

- area ``000``, ``666``, or ``900-999``
- group ``00``
- serial ``0000``

This is a structural check only; it cannot tell whether a well-formed SSN
was ever actually issued to someone.
"""

from __future__ import annotations

import re

from veil.types import Entity, EntityType, Span

_SSN_RE = re.compile(r"(?<!\d)(?P<area>\d{3})[- ]?(?P<group>\d{2})[- ]?(?P<serial>\d{4})(?!\d)")


def is_valid_ssn(area: str, group: str, serial: str) -> bool:
    if area == "000" or area == "666" or area[0] == "9":
        return False
    if group == "00":
        return False
    return serial != "0000"


class SsnDetector:
    name = "ssn"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _SSN_RE.finditer(text):
            if not is_valid_ssn(m.group("area"), m.group("group"), m.group("serial")):
                continue
            # Require at least one separator, or explicit "SSN"/"social security"
            # context nearby, to avoid matching arbitrary 9-digit numbers.
            has_sep = "-" in m.group(0) or " " in m.group(0)
            if not has_sep:
                window = text[max(0, m.start() - 25) : m.start()].lower()
                if "ssn" not in window and "social security" not in window:
                    continue
            out.append(
                Entity(
                    type=EntityType.SSN,
                    value=m.group(0),
                    span=Span(m.start(), m.end()),
                    detector=self.name,
                    confidence=0.9 if has_sep else 0.6,
                )
            )
        return out
