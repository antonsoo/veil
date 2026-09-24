"""US street address detector (heuristic, opt-in).

Addresses have no checksum and no closed grammar, so this is the weakest
detector in veil: a regex for ``<number> <street name> <suffix>``, with an
optional unit and a US Postal Service suffix list. It will miss unusual
formats and can match things that only look like addresses. Not enabled by
default — pass ``include_address=True`` to :class:`veil.masker.Masker`.
"""

from __future__ import annotations

import re

from veil.types import Entity, EntityType, Span

_SUFFIXES = (
    "Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Court|Ct|Lane|Ln|Road|Rd|"
    "Way|Place|Pl|Terrace|Ter|Circle|Cir|Trail|Trl|Parkway|Pkwy|Square|Sq|"
    "Highway|Hwy"
)

_ADDRESS_RE = re.compile(
    rf"\b\d{{1,6}}\s+(?:[A-Z][a-zA-Z'.-]*\s){{1,4}}(?:{_SUFFIXES})\b\.?"
    rf"(?:\s*,?\s*(?:Apt|Suite|Ste|Unit|#)\s*\.?\s*[A-Za-z0-9-]+)?",
)


class AddressDetector:
    name = "address"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _ADDRESS_RE.finditer(text):
            out.append(
                Entity(
                    type=EntityType.ADDRESS,
                    value=m.group(0),
                    span=Span(m.start(), m.end()),
                    detector=self.name,
                    confidence=0.5,
                )
            )
        return out
