"""Email address detector.

Uses a pragmatic regex (not full RFC 5322 — nobody implements that faithfully
and it over-matches on real text) followed by a couple of structural checks:
no consecutive dots, label lengths under 64, and a TLD that is alphabetic and
at least two characters.
"""

from __future__ import annotations

import re

from veil.types import Entity, EntityType, Span

_EMAIL_RE = re.compile(
    r"(?<![\w.+'-])"
    r"(?P<local>[A-Za-z0-9_][A-Za-z0-9._%+'-]{0,63})"
    r"@"
    r"(?P<domain>[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*"
    r"\.(?P<tld>[A-Za-z]{2,24}))"
    r"(?![\w+-])"
)


def _is_valid(local: str, domain: str) -> bool:
    if ".." in local or ".." in domain:
        return False
    if local.startswith(".") or local.endswith("."):
        return False
    return not any(len(label) > 63 for label in domain.split("."))


class EmailDetector:
    name = "email"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _EMAIL_RE.finditer(text):
            if not _is_valid(m.group("local"), m.group("domain")):
                continue
            out.append(
                Entity(
                    type=EntityType.EMAIL,
                    value=m.group(0),
                    span=Span(m.start(), m.end()),
                    detector=self.name,
                )
            )
        return out
