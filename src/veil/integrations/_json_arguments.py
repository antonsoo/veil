"""Transform decoded JSON values without rewriting surrounding argument syntax."""

from __future__ import annotations

import json
from dataclasses import dataclass

from veil.masker import Masker
from veil.restore import restore_json_text
from veil.vault import VaultError


def _reject_constant(value: str) -> None:
    raise ValueError("Non-JSON numeric constant")


@dataclass(frozen=True)
class _StringToken:
    start: int
    end: int
    value: str
    is_key: bool


def mask_string_value(value: str, masker: Masker, *, key: str | None = None) -> str:
    """Retain an explicit credential field's context for its string value.

    The prefix is only a detector hint, never a changed key or output field.
    Masker's ordinary request transaction, reservations and exact restoration
    checks still apply to the complete contextual text.
    """
    if key is not None and key.lower() in {"authorization", "proxy-authorization"}:
        prefix = "Authorization: "
        return masker.mask(prefix + value)[len(prefix) :]
    return masker.mask(value, field_name=key)


def _string_tokens(arguments: str) -> list[_StringToken]:
    # Numbers are only validated, never converted to bounded ints or floats.
    json.loads(arguments, parse_int=str, parse_float=str, parse_constant=_reject_constant)
    decoder = json.JSONDecoder()
    tokens: list[_StringToken] = []
    pos = 0
    while (start := arguments.find('"', pos)) != -1:
        value, end = decoder.raw_decode(arguments, start)
        assert isinstance(value, str)
        pos = end
        while pos < len(arguments) and arguments[pos] in " \t\r\n":
            pos += 1
        tokens.append(
            _StringToken(start, end, value, pos < len(arguments) and arguments[pos] == ":")
        )
    return tokens


def _replace_values(arguments: str, tokens: list[_StringToken], replacements: list[str]) -> str:
    pieces: list[str] = []
    pos = 0
    for token, replacement in zip(tokens, replacements, strict=True):
        if replacement != token.value:
            pieces.append(arguments[pos : token.start])
            pieces.append(json.dumps(replacement, ensure_ascii=False))
            pos = token.end
    pieces.append(arguments[pos:])
    return "".join(pieces)


def mask_arguments(arguments: str, masker: Masker) -> str:
    """Mask string values in a complete JSON argument document.

    Scanning the raw document misses entities containing JSON escapes. Re-encoding
    the entire parsed tree, however, changes numeric precision, duplicate members
    and unrelated spelling. Validate first, then replace only changed string tokens.
    Field names cannot safely be renamed; detected sensitive keys reject the request.
    Non-string values retain their types and are outside string-masking coverage.
    """
    try:
        tokens = _string_tokens(arguments)
    except (ValueError, RecursionError):
        raise VaultError("Tool arguments must be complete, valid JSON before masking") from None
    for token in tokens:
        if token.is_key and masker.find_entities(token.value):
            raise VaultError(
                "Tool arguments contain a sensitive JSON key; use a non-sensitive field name"
            )
    values: list[tuple[_StringToken, str | None]] = []
    for index, token in enumerate(tokens):
        if token.is_key:
            continue
        previous = tokens[index - 1] if index else None
        # A key supplies context only to its immediate string value. Arrays
        # and nested objects must not inherit a header name from an ancestor.
        key = (
            previous.value
            if previous is not None
            and previous.is_key
            and arguments[previous.end : token.start].strip() == ":"
            else None
        )
        values.append((token, key))
    # Reserve all decoded literal text together, including escaped placeholder
    # examples, so one value cannot acquire another value's existing literal token.
    with masker._masking_batch() as batch:
        for token, _ in values:
            batch.reserve(token.value)
        masked = [mask_string_value(token.value, masker, key=key) for token, key in values]
    return _replace_values(arguments, [token for token, _ in values], masked)


def restore_arguments(arguments: str, masker: Masker) -> str:
    """Restore complete string values without coercing unrelated tool data.

    Complete values retain tolerant restoration. For malformed or truncated model
    output, the streaming lexer still makes its existing best effort without
    inventing syntax. Neither path renames keys or converts numeric tokens.
    """
    try:
        values = [token for token in _string_tokens(arguments) if not token.is_key]
    except (ValueError, RecursionError):
        return restore_json_text(arguments, masker.vault)
    return _replace_values(arguments, values, [masker.restore(token.value) for token in values])
