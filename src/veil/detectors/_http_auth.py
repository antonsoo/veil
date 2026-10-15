"""Recognize explicit HTTP Basic/Bearer credentials, without authenticating them.

The field name supplies the signal that entropy cannot: short or repetitive
credentials still need protection. Keep the complete token68 value, including
padding and punctuation, rather than selecting recognizable fragments in it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

# Recognize raw headers and their usual quoted JSON/dict/curl representations.
# Horizontal whitespace cannot join an empty header to a following log line.
# The final boundary refuses a shorter prefix of a glued unsupported value.
# Basic's payload stays opaque too: malformed/expired credentials can be private.
_AUTHORIZATION = re.compile(
    r"(?<![\w-])(?ai:(?:Proxy-)?Authorization)[\"']?[ \t]*:[ \t]*[\"']?"
    r"(?ai:Basic|Bearer)[ \t]+(?P<credential>[A-Za-z0-9._~+/-]+=*)"
    r"(?=$|[\s\"'<>,;)}\]]|\\)"
)


def http_authorization_spans(text: str) -> Iterator[tuple[int, int]]:
    """Complete credential spans; field names and auth schemes remain readable."""
    for match in _AUTHORIZATION.finditer(text):
        yield match.span("credential")
