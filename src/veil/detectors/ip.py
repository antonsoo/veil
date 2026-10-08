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


# A dotted quad labelled as a version ("v2.4.1.0", "version 10.2.14.3",
# "build 1.0.0.7") is not an address, however valid it would be as one. Nor
# is the version in a browser's product token ("Chrome/126.0.0.0") or the last
# field of a Windows package identity ("...~amd64~~6.1.1.3").
_VERSION_LABEL_RE = re.compile(
    r"(?:\bv|\b(?:version|ver\.?|build|release|firmware)\s*[:=]?\s*"
    r"|\b(?:Chrome|Chromium|HeadlessChrome|CriOS|Edg|Edge|EdgA|OPR|Firefox|FxiOS|Safari|Version"
    r"|AppleWebKit|Electron|Trident)/"
    r"|~)$",
    re.IGNORECASE,
)


def _is_nobodys(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether an address identifies no host: there is nothing to protect in it.

    The unspecified address (``0.0.0.0``, ``::``), loopback (``127.0.0.1``,
    ``::1``), and the space the IETF holds in reserve, which for IPv6 is
    everything not yet handed out: ``::`` alone, the ``1::2`` of a Python
    slice and the ``be::`` of "it would be::" in reStructuredText all parse
    as addresses there. Masking them hides nobody and takes the bind address
    out of a log.
    """
    return address.is_unspecified or address.is_loopback or address.is_reserved


class IpDetector:
    name = "ip"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _IPV4_RE.finditer(text):
            try:
                v4 = ipaddress.IPv4Address(m.group(0))
            except ValueError:
                continue
            if _is_nobodys(v4):
                continue
            if _VERSION_LABEL_RE.search(text[max(0, m.start() - 16) : m.start()]):
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
                v6 = ipaddress.IPv6Address(candidate)
            except ValueError:
                continue
            if _is_nobodys(v6):
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
