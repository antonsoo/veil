"""Recognize compact JWT-shaped credentials without authenticating them.

Only the bounded JOSE header is decoded. Claims stay opaque: masking must not
depend on a signature being valid, a token being unexpired, or a claim's value.
No signature algorithm runs and no key URL is followed.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterator

MAX_JWT_HEADER_CHARS = 16_384
_PART = r"[A-Za-z0-9_-]+={0,2}"
_COMPACT = re.compile(
    rf"(?<![\w.-])(?P<header>{_PART})\.(?P<payload>{_PART})\."
    r"(?P<signature>[A-Za-z0-9_-]*={0,2})"
    # A sentence's final dots are outside the token. An additional encoded
    # segment is not punctuation: never select three parts out of a JWE.
    r"(?=$|[^\w.=-]|\.+(?=$|[^\w.=-]))"
)


def compact_jwt_spans(text: str) -> Iterator[tuple[int, int]]:
    """Complete supported token spans; this is recognition, not JWT validation."""
    for match in _COMPACT.finditer(text):
        if match.end("header") - match.start("header") > MAX_JWT_HEADER_CHARS:
            continue
        encoded = match.group("header")
        try:
            decoded = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            )
            header = json.loads(decoded.decode("utf-8"))
        except (ValueError, RecursionError):
            continue
        if not isinstance(header, dict) or "enc" in header:
            continue
        algorithm = header.get("alg")
        if not isinstance(algorithm, str) or not algorithm.strip():
            continue
        if not match.group("signature") and algorithm != "none":
            continue
        yield match.start(), match.end()
