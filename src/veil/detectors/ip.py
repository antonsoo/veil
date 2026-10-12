"""IPv4 and IPv6 address detector.

Candidate spans are matched with a cheap regex, then handed to the stdlib
``ipaddress`` module for authoritative parsing — this avoids re-deriving
IPv6's many valid shorthand forms (``::``, embedded IPv4, zone IDs) by hand.
"""

from __future__ import annotations

import ipaddress
import re

from veil._spans import SpanIndex
from veil.types import Entity, EntityType, Span

# Trailing lookahead: block a following word char (glued alphanumeric) and
# specifically "another dotted digit" (a 5th octet - not a valid IPv4, so
# this candidate is really a prefix of some other dotted-number sequence).
# A bare trailing "." that *isn't* followed by a digit (ordinary sentence
# punctuation, e.g. "...at 10.0.0.1.") is deliberately allowed through.
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w)(?!\.\d)")
# Consume the whole literal before validation. A hex-only expression can accept
# the valid prefix "2001:db8::192" of "2001:db8::192.0.2.33", exposing the rest.
# Zone identifiers are opaque local names/indices; retain their spelling,
# including percent escapes in bracketed URI literals, without resolving them.
_IPV6_RE = re.compile(
    r"(?<![\w:%.])[0-9A-Fa-f]*:[0-9A-Fa-f:]*(?:\.[0-9][0-9A-Fa-f:]*)*"
    r"(?:%[\w.%:~+\-]*)?(?![\w:%])(?!\.\d)"
)
_ZONE_RE = re.compile(r"(?:[\w.~\-]|%[0-9A-Fa-f]{2})+")

# These assigned prefixes still fall within ipaddress's broad reserved ranges.
# They can identify translated endpoints / routing segments, not merely code
# resembling an address. IANA IPv6 Special-Purpose Address Registry; RFCs
# 6052, 8215 and 9602. Other reserved-space exclusions remain in effect.
_ASSIGNED_RESERVED = tuple(
    ipaddress.IPv6Network(prefix) for prefix in ("64:ff9b::/96", "64:ff9b:1::/48", "5f00::/16")
)


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
    ``::1``), and most reserved space are excluded. This keeps bind addresses
    readable and avoids treating the ``1::2`` of a Python slice or the ``be::``
    of reStructuredText as a host. Assigned translation/routing prefixes are
    exceptions to the reserved-space filter. Mapped addresses follow IPv4's
    classification regardless of their textual representation.
    """
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return _is_nobodys(address.ipv4_mapped)
        if any(address in network for network in _ASSIGNED_RESERVED):
            return False
    return address.is_unspecified or address.is_loopback or address.is_reserved


class IpDetector:
    name = "ip"

    def find(self, text: str) -> list[Entity]:
        ipv6: list[Entity] = []
        literals: list[Span] = []
        for m in _IPV6_RE.finditer(text):
            candidate = m.group(0).rstrip(".")  # prose punctuation is outside the address
            address, separator, zone = candidate.partition("%")
            if address.count(":") < 2:
                continue
            # Even an invalid IPv6-shaped token must not yield a valid IPv4
            # fragment. Keep its full span when suppressing embedded matches.
            literals.append(Span(m.start(), m.end()))
            if len(address) > 45 or (separator and not _ZONE_RE.fullmatch(zone)):
                continue
            try:
                v6 = ipaddress.IPv6Address(address)
            except ValueError:
                continue
            if v6.is_unspecified or v6.is_loopback:
                continue
            if _is_nobodys(v6):
                # An explicit dotted tail already established an IPv4 identity
                # in the old detector. Protect the enclosing literal, including
                # deprecated IPv4-compatible notation, instead of its tail alone.
                # Low bits 127.0.0.1 do not make a global IPv6 address loopback.
                # Use this fallback only for otherwise excluded reserved space.
                if "." not in address or v6.ipv4_mapped is not None:
                    continue
                if _is_nobodys(ipaddress.IPv4Address(address.rsplit(":", 1)[1])):
                    continue
            ipv6.append(
                Entity(
                    type=EntityType.IPV6,
                    value=candidate,
                    span=Span(m.start(), m.start() + len(candidate)),
                    detector=self.name,
                )
            )
        ipv6_spans = SpanIndex(literals)
        out: list[Entity] = []
        for m in _IPV4_RE.finditer(text):
            if ipv6_spans.overlaps(Span(m.start(), m.end())):
                continue
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
        out.extend(ipv6)
        return out
