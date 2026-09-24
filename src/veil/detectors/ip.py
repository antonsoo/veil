"""IPv4 and IPv6 address detector.

Candidate spans are matched with a cheap regex, then handed to the stdlib
``ipaddress`` module for authoritative parsing — this avoids re-deriving
IPv6's many valid shorthand forms (``::``, embedded IPv4, zone IDs) by hand.
"""

from __future__ import annotations

import ipaddress
import re

from veil.types import Entity, EntityType, Span

# Trailing lookahead: block a following word char (glued alphanumeric) and
# specifically "another dotted digit" (a 5th octet - not a valid IPv4, so
# this candidate is really a prefix of some other dotted-number sequence).
# A bare trailing "." that *isn't* followed by a digit (ordinary sentence
# punctuation, e.g. "...at 10.0.0.1.") is deliberately allowed through.
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w)(?!\.\d)")
_IPV6_RE = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")


class IpDetector:
    name = "ip"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _IPV4_RE.finditer(text):
            try:
                ipaddress.IPv4Address(m.group(0))
            except ValueError:
                continue
            out.append(
                Entity(
                    type=EntityType.IPV4,
                    value=m.group(0),
                    span=Span(m.start(), m.end()),
                    detector=self.name,
                )
            )
        for m in _IPV6_RE.finditer(text):
            candidate = m.group(0)
            if candidate.count(":") < 2:
                continue
            try:
                ipaddress.IPv6Address(candidate)
            except ValueError:
                continue
            out.append(
                Entity(
                    type=EntityType.IPV6,
                    value=candidate,
                    span=Span(m.start(), m.end()),
                    detector=self.name,
                )
            )
        return out
