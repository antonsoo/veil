"""US street address detector (heuristic, opt-in).

Addresses have no checksum and no closed grammar, so this is the weakest
detector in veil: a regex for ``<number> <street name> <suffix>``, with an
optional compass point and unit and a US Postal Service suffix list. It
will miss unusual formats and can match things that only look like
addresses. Not enabled by default — pass ``include_address=True`` to :class:`veil.masker.Masker`.
"""

from __future__ import annotations

import re

from veil.types import Entity, EntityType, Span

_SUFFIXES = (
    "Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Court|Ct|Lane|Ln|Road|Rd|"
    "Way|Place|Pl|Terrace|Ter|Circle|Cir|Trail|Trl|Parkway|Pkwy|Square|Sq|"
    "Highway|Hwy"
)

# No trailing `\.?` after the suffix: a period there is ambiguous between
# an abbreviation ("St.") and a sentence-ending full stop ("... Court."),
# and swallowing the latter into the match is the worse failure mode.
# A street name is capitalized words, or a number street: "West 32nd Street",
# "9th Avenue". After the suffix a compass point may follow ("Park Avenue
# South", "Bloor Street West"); a single letter counts only where the address
# plainly ends, so "12 Oak Street W." is one and "Oak Street E of the river"
# stops at Street.
_NAME_WORD = r"(?:[A-Z][a-zA-Z'.-]*|\d{1,3}(?:st|nd|rd|th))"
_COMPASS = r"(?:North|South|East|West|NE|NW|SE|SW)\b|[NSEW](?=\s*(?:[,.;\n]|$))"
_ADDRESS_RE = re.compile(
    rf"\b\d{{1,6}}[A-Za-z]?(?:-\d{{1,6}})?\s+(?:{_NAME_WORD}\s){{1,4}}(?:{_SUFFIXES})\b"
    rf"(?:\s(?:{_COMPASS}))?"
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
