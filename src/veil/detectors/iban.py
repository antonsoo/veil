"""IBAN (International Bank Account Number) detector.

Validates the ISO 7064 MOD 97-10 checksum and the fixed length registered
for each country in the IBAN registry (SWIFT/ISO 13616). Both checks must
pass, which makes false positives rare: a random alphanumeric string of the
right shape has roughly a 1-in-97 chance of passing the checksum.
"""

from __future__ import annotations

import re

from veil.types import Entity, EntityType, Span

# Registered IBAN length per country, from the IBAN registry (release 96,
# Society for Worldwide Interbank Financial Telecommunication / ISO 13616).
_COUNTRY_LENGTHS: dict[str, int] = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16,
    "BG": 22, "BH": 22, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28,
    "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24,
    "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18,
    "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IQ": 23,
    "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32,
    "LI": 21, "LT": 20, "LU": 20, "LV": 21, "LY": 25, "MC": 27, "MD": 24,
    "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22,
    "SA": 24, "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24, "SM": 27,
    "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22,
    "VG": 24, "XK": 20,
}  # fmt: skip

# IBANs are conventionally printed in uppercase (ISO 13616); requiring
# uppercase here keeps ordinary lowercase prose words from being pulled
# into a trailing group (e.g. "... 0130 00 by" would otherwise swallow "by").
_CANDIDATE_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{1,4}){2,7}\b")


def _mod97_ok(compact: str) -> bool:
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def is_valid_iban(candidate: str) -> bool:
    compact = candidate.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", compact):
        return False
    country = compact[:2]
    expected_len = _COUNTRY_LENGTHS.get(country)
    if expected_len is None or len(compact) != expected_len:
        return False
    return _mod97_ok(compact)


class IbanDetector:
    name = "iban"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _CANDIDATE_RE.finditer(text):
            if not is_valid_iban(m.group(0)):
                continue
            out.append(
                Entity(
                    type=EntityType.IBAN,
                    value=m.group(0),
                    span=Span(m.start(), m.end()),
                    detector=self.name,
                    confidence=0.99,
                )
            )
        return out
