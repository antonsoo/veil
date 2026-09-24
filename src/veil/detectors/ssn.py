"""US Social Security Number detector.

Matches ``AAA-GG-SSSS`` (with `-`, ` `, or no separator, used
*consistently* — see below) and excludes area, group, and serial values
the SSA has documented as never issued:

- area ``000``, ``666``, or ``900-999``
- group ``00``
- serial ``0000``

**Consistent-separator requirement.** A US ZIP+4 code (``AAAAA-SSSS``, 5
digits, a dash, 4 digits) is structurally a false positive here: read as
area(3)+group(2)+sep+serial(4), "22156-7224" parses as a well-formed SSN.
Real SSNs are written with a separator at *both* gaps or *neither* —
never one. Requiring the two separators to match rejects the ZIP+4 shape
(no separator before the 2-digit group, one before the last 4) without
needing to special-case "ZIP".

This is a structural check only; it cannot tell whether a well-formed SSN
was ever actually issued to someone.
"""

from __future__ import annotations

import re

from veil.types import Entity, EntityType, Span

_SSN_RE = re.compile(
    r"(?<!\d)(?P<area>\d{3})(?P<sep1>[- ]?)(?P<group>\d{2})(?P<sep2>[- ]?)(?P<serial>\d{4})(?!\d)"
)


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
            if m.group("sep1") != m.group("sep2"):
                continue  # e.g. a ZIP+4 code, not a consistently-formatted SSN
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
