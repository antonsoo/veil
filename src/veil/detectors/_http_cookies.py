"""Opaque values of explicit Cookie and Set-Cookie headers.

Cookie names and entropy cannot identify which member authorizes a session.
Keep the complete field value together, including Set-Cookie's Expires comma.
This is a bounded text recognizer, not a cookie parser or a HAR interpreter.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

_HEADER = re.compile(
    r"(?<![\w.-])(?P<keyquote>[\"']?)(?ai:Set-Cookie|Cookie)(?P=keyquote)"
    r"[ \t]*:[ \t]*"
)


def is_cookie_field(name: str) -> bool:
    return name.lower() in {"cookie", "set-cookie"}


def _quoted_end(text: str, start: int, quote: str) -> int:
    pos = start
    while pos < len(text) and text[pos] not in "\r\n":
        if text[pos] == quote:
            return pos
        if text[pos] == "\\" and pos + 1 < len(text) and text[pos + 1] not in "\r\n":
            pos += 1
        pos += 1
    return min(pos, len(text))


def http_cookie_spans(text: str) -> Iterator[tuple[int, int]]:
    """Raw headers, quoted mapping values and quoted curl header arguments.

    Quoted source escapes remain source text. Unquoted values end at the
    physical line; obsolete folded headers and shell concatenation are outside
    this grammar. A missing closing quote consumes only its first line.
    """
    pos = 0
    while (match := _HEADER.search(text, pos)) is not None:
        start = match.end()
        # A curl quote starts before the field name, whereas a mapping's
        # closing key quote is already part of the header match.
        outer = text[match.start() - 1] if match.start() else ""
        quote = outer if outer in {"'", '"'} else ""
        if start < len(text) and text[start] in {"'", '"'}:
            quote = text[start]
            start += 1
        if quote:
            end = _quoted_end(text, start, quote)
            pos = end + 1
        else:
            end = start
            while end < len(text) and text[end] not in "\r\n":
                end += 1
            pos = max(end, match.end())
        while end > start and text[end - 1] in " \t":
            end -= 1
        if end > start:
            yield start, end
