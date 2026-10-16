"""Bounded credential assignments; recognition, not a configuration parser.

An explicit label supplies the signal that a short password lacks. Preserve
the label and surrounding syntax, and select a complete value. Quoted raw
text retains its source escapes; decoded SDK values take a separate field
context path so their original value is stored without invented escaping.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

# No bare `secret`, `token` or `pwd`: these commonly describe other things.
# Environment prefixes require uppercase spelling, rather than interpreting
# arbitrary prose identifiers ending in "password" as credential fields.
_LABEL = (
    r"(?ai:password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token|"
    r"refresh[_-]?token|x-api-key)"
    r"|[A-Z][A-Z0-9_]*_(?:PASSWORD|PASSWD|API_KEY|CLIENT_SECRET|ACCESS_TOKEN|REFRESH_TOKEN)"
)
_FIELD_NAME = re.compile(rf"(?:{_LABEL})\Z")
_ASSIGNMENT = re.compile(
    rf"(?<![\w./?&%#:-])(?:(?P<quote>[\"'])(?:{_LABEL})(?P=quote)|(?:{_LABEL}))(?![\w-])"
    r"[ \t]*[:=](?!=)[ \t]*"
)
_BARE_VALUE = re.compile(r"[^\s\"'`,;{}\[\]()<>|\\]+")
# A block header must begin a mapping entry, optionally in a compact sequence.
# The digit is relative to the key's column; no YAML dependency or decoding is
# needed to keep the source body opaque. Tags, anchors and explicit keys are
# outside this deliberately bounded recognizer.
_BLOCK_FIELD = re.compile(
    rf"(?:\A\ufeff?|(?<=[\r\n]))(?P<prefix> *(?:- +)*)"
    rf"(?:(?P<quote>[\"'])(?:{_LABEL})(?P=quote)|(?:{_LABEL}))[ \t]*:[ \t]*"
    r"[|>](?P<indicators>(?:[1-9][+-]?|[+-][1-9]?)?)[ \t]*"
    r"(?:#[^\r\n]*)?(?:\r\n|\r|\n|\Z)"
)
_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n|\Z)")
_NON_STRING = frozenset(
    {
        "null",
        "none",
        "true",
        "false",
        "undefined",
        "str",
        "string",
        "bytes",
        "int",
        "float",
        "bool",
        "object",
        "any",
    }
)


def is_credential_field(name: str) -> bool:
    """Exact supported label, including uppercase environment-style prefixes."""
    return _FIELD_NAME.fullmatch(name) is not None


def _quoted_end(text: str, start: int) -> int:
    quote = text[start]
    pos = start + 1
    while pos < len(text) and text[pos] not in "\r\n":
        if text[pos] == quote:
            return pos
        if text[pos] == "\\":
            pos += 1
            if pos >= len(text) or text[pos] in "\r\n":
                break
        pos += 1
    # Return the stopping position as well on failure: the caller skips the
    # malformed value instead of repeatedly scanning the same suffix.
    return -pos - 1


def _yaml_block_spans(text: str) -> Iterator[tuple[int, int]]:
    """Indented literal/folded credential bodies, without reserializing YAML.

    Keep the header, required indentation and final line break in place, so
    the replacement is still a block scalar. The raw span owns internal line
    breaks, extra indentation, comment-looking text and nested PII together.
    Blank lines at either edge need no replacement. Dedented entries/comments
    remain outside the credential, including a later non-credential block.
    """
    pos = 0
    while (header := _BLOCK_FIELD.search(text, pos)) is not None:
        base_indent = len(header["prefix"])
        digit = next((int(c) for c in header["indicators"] if c.isdigit()), None)
        indent = base_indent + digit if digit is not None else None
        pos = header.end()
        start = end = None
        while pos < len(text):
            line = _LINE.match(text, pos)
            assert line is not None
            content = line.group().rstrip("\r\n")
            if content.strip(" "):
                spaces = len(content) - len(content.lstrip(" "))
                if spaces <= base_indent or (indent is not None and spaces < indent):
                    break
                if indent is None:
                    indent = spaces
                if start is None:
                    start = pos + indent
                end = pos + len(content)
            pos = line.end()
        if start is not None and end is not None and end > start:
            yield start, end


def credential_field_spans(text: str) -> Iterator[tuple[int, int]]:
    """Complete nonempty quoted or bounded unquoted assignment values.

    Horizontal spacing cannot join an empty field to the next log line.
    Literal/folded YAML bodies use indentation boundaries. Arrays, objects,
    shell references and obvious function-call expressions are not treated as
    string credentials. This does not evaluate shell, Python or interpolation,
    or parse arbitrary YAML; malformed/unsupported syntax can be missed.
    """
    blocks = iter(_yaml_block_spans(text))
    block = next(blocks, None)
    pos = 0
    while (match := _ASSIGNMENT.search(text, pos)) is not None:
        if block is not None and match.start() >= block[0]:
            # Publish the enclosing value before any assignment-like text in
            # its body can fragment it. Resume after the whole source span.
            yield block
            pos = block[1]
            block = next(blocks, None)
            continue
        start = pos = match.end()
        if start >= len(text) or text[start] in "\r\n":
            continue
        if text[start] in "\"'":
            end = _quoted_end(text, start)
            if end < 0:
                pos = -end - 1
                continue
            pos = end + 1
            if pos < len(text) and not (text[pos].isspace() or text[pos] in "\"',;)}]"):
                continue
            if end > start + 1:
                yield start + 1, end
        elif text[start] not in "$#":
            value = _BARE_VALUE.match(text, start)
            if value is None:
                continue
            pos = value.end()
            # Do not disguise a shorter prefix of get_password() or a
            # backslash-escaped value as a complete credential.
            if pos < len(text) and text[pos] in "([{\\":
                continue
            if value.group().casefold() not in _NON_STRING:
                yield start, pos
    if block is not None:
        yield block
        yield from blocks
