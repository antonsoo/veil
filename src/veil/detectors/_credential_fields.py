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
    r"[ \t]*(?P<separator>[:=])(?!=)[ \t]*"
)
_BARE_VALUE = re.compile(r"[^\s\"'`,;{}\[\]()<>\\]+")
# A block header must begin a mapping entry, optionally in a compact sequence.
# The digit is relative to the key's column; no YAML dependency or decoding is
# needed to keep the source body opaque. Tags, anchors and explicit keys are
# outside this deliberately bounded recognizer.
_BLOCK_INDICATOR = r"[|>](?P<indicators>(?:[1-9][+-]?|[+-][1-9]?)?)[ \t]*"
# Only peek at a following comment marker. Consuming its whole line for every
# assignment-looking substring in the comment would rescan the suffix.
_BLOCK_VALUE = re.compile(_BLOCK_INDICATOR + r"(?=#|\r|\n|\Z)")
_BLOCK_FIELD = re.compile(
    rf"(?:\A\ufeff?|(?<=[\r\n]))(?P<prefix> *(?:- +)*)"
    rf"(?:(?P<quote>[\"'])(?:{_LABEL})(?P=quote)|(?:{_LABEL}))[ \t]*:[ \t]*"
    + _BLOCK_INDICATOR
    + r"(?:#[^\r\n]*)?(?:\r\n|\r|\n|\Z)"
)
_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n|\Z)")
_YAML_FIELD = re.compile(
    rf"(?:\A\ufeff?|(?<=[\r\n]))(?P<prefix> *(?:- +)*)"
    rf"(?:(?P<quote>[\"'])(?:{_LABEL})(?P=quote)|(?:{_LABEL}))[ \t]*:"
    r"(?:[ \t]+|(?=[\r\n]|\Z))"
)
_PLAIN_SPECIAL = re.compile(r"[ \t]+#|:(?=[ \t\r\n]|\Z)")
_LOG_TAIL = re.compile(r"[,;](?=[ \t]+[\w.-]+[ \t]*[:=])")
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


def _quoted_end(text: str, start: int, yaml_indent: int | None = None) -> int:
    """Closing quote, or the complemented stopping position on failure.

    YAML single quotes escape an apostrophe by doubling it; backslashes are
    literal. Mapping values may wrap onto indented continuation lines. The
    indentation boundary deliberately leaves a malformed paste's next mapping
    available to the assignment scanner. Unindented YAML flow continuations
    and flow collections are outside this bounded source recognizer.
    """
    quote = text[start]
    pos = start + 1
    while pos < len(text):
        if text[pos] in "\r\n":
            if yaml_indent is None:
                break
            line_start = pos + (2 if text.startswith("\r\n", pos) else 1)
            content = line_start
            while content < len(text) and text[content] == " ":
                content += 1
            if (
                content < len(text)
                and text[content] not in "\r\n"
                and content - line_start <= yaml_indent
            ):
                return -line_start - 1
            pos = content
            continue
        if text[pos] == quote:
            if yaml_indent is not None and quote == "'" and text.startswith("''", pos):
                pos += 2
                continue
            return pos
        if text[pos] == "\\" and not (yaml_indent is not None and quote == "'"):
            pos += 1
            if pos >= len(text):
                break
            if text[pos] in "\r\n":
                if yaml_indent is None:
                    break
                continue
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


def _next_yaml_scalar(text: str, start: int, indent: int) -> int | None:
    """An indented scalar after an empty header, without crossing a sibling."""
    pos = start
    while pos < len(text):
        if text[pos] in "\r\n":
            pos += 2 if text.startswith("\r\n", pos) else 1
        line_start = pos
        while pos < len(text) and text[pos] == " ":
            pos += 1
        if pos == len(text):
            return None
        if text[pos] not in "\r\n":
            return pos if pos - line_start > indent and text[pos] != "#" else None
    return None


def _plain_end(text: str, start: int, indent: int) -> int | None:
    """End of a plain YAML mapping scalar, keeping comments and neighbors.

    Collections, node properties and references are outside this recognizer.
    A colon followed by whitespace belongs to
    mapping syntax, never to a plain scalar's contents. Do not absorb such a
    later line from a damaged paste into the preceding credential.
    """
    if text[start] in "[{]},!&*|>'\"%@`#$" or (
        text[start] in "-?:" and (start + 1 == len(text) or text[start + 1].isspace())
    ):
        return None
    pos = start
    end = None
    while pos < len(text):
        line = _LINE.match(text, pos)
        assert line is not None
        content = line.group().rstrip("\r\n")
        if pos != start:
            spaces = len(content) - len(content.lstrip(" "))
            if content.strip(" ") and (spaces <= indent or content[spaces] == "#"):
                break
        special = _PLAIN_SPECIAL.search(content)
        if special is not None and content[special.start()] == ":":
            break
        tail = _LOG_TAIL.search(content)
        if tail is not None and (special is None or tail.start() < special.start()):
            special = tail
        data = content[: special.start()] if special is not None else content
        data = data.rstrip(" \t")
        if data.strip(" "):
            end = pos + len(data)
        if special is not None:
            break
        pos = line.end()
    return end


def credential_field_spans(text: str) -> Iterator[tuple[int, int]]:
    """Complete nonempty quoted or bounded unquoted assignment values.

    Horizontal spacing cannot join an empty field to the next log line.
    YAML mapping bodies use indentation boundaries. Arrays, objects,
    shell references and obvious function-call expressions are not treated as
    string credentials. This does not evaluate shell, Python or interpolation,
    or parse arbitrary YAML; malformed/unsupported syntax can be missed.
    """
    blocks = iter(_yaml_block_spans(text))
    block = next(blocks, None)
    yaml_fields = iter(_YAML_FIELD.finditer(text))
    yaml_field = next(yaml_fields, None)
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
        if start >= len(text):
            continue
        # A forward-only header iterator avoids rescanning a long line
        # backwards for every assignment in it.
        while yaml_field is not None and yaml_field.end() < start:
            yaml_field = next(yaml_fields, None)
        yaml_indent = (
            len(yaml_field["prefix"])
            if yaml_field is not None and yaml_field.end() == start
            else None
        )
        if text[start] in "\r\n":
            following = (
                _next_yaml_scalar(text, start, yaml_indent) if yaml_indent is not None else None
            )
            if following is None:
                continue
            start = pos = following
        if match["separator"] == ":" and text[start] == "|" and _BLOCK_VALUE.match(text, start):
            # A complete block indicator is syntax, including an empty block.
            # A pipe inside a bare credential (or after '=') remains value data.
            continue
        if text[start] in "\"'":
            end = _quoted_end(text, start, yaml_indent)
            if end < 0:
                pos = -end - 1
                continue
            pos = end + 1
            if pos < len(text) and not (
                text[pos].isspace()
                or text[pos] in ",;)}]"
                or (yaml_indent is not None and text[pos] == "#")
            ):
                continue
            if end > start + 1:
                yield start + 1, end
            # Block-looking text inside a quoted scalar is credential data,
            # not an independent YAML body to publish on a later iteration.
            while block is not None and block[0] < pos:
                block = next(blocks, None)
        elif yaml_indent is not None:
            plain_end = _plain_end(text, start, yaml_indent)
            if plain_end is not None:
                pos = plain_end
                # Raw text may be a type annotation rather than YAML. Retain
                # the existing type-word exclusion with its statement terminator.
                if text[start:plain_end].casefold().removesuffix(";") not in _NON_STRING:
                    yield start, plain_end
                while block is not None and block[0] < pos:
                    block = next(blocks, None)
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
