"""IPv4 and IPv6 address detector.

Candidate spans are matched with a cheap regex, then handed to the stdlib
``ipaddress`` module for authoritative parsing — this avoids re-deriving
IPv6's many valid shorthand forms (``::``, embedded IPv4, zone IDs) by hand.
"""

from __future__ import annotations

import ipaddress
import re

from veil.types import Entity, EntityType, Span

_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
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
