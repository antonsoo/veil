"""Mask decoded JSON values without rewriting the surrounding argument syntax."""

from __future__ import annotations

import json

from veil.masker import Masker
from veil.vault import VaultError


def _reject_constant(value: str) -> None:
    raise ValueError("Non-JSON numeric constant")


def mask_arguments(arguments: str, masker: Masker) -> str:
    """Mask string values in a complete JSON argument document.

    Scanning the raw document misses entities containing JSON escapes. Re-encoding
    the entire parsed tree, however, changes numeric precision, duplicate members
    and unrelated spelling. Validate first, then replace only changed string tokens.
    Field names cannot safely be renamed; detected sensitive keys reject the request.
    Non-string values retain their types and are outside string-masking coverage.
    """
    try:
        # Numbers are only validated, never converted to bounded ints or floats.
        json.loads(arguments, parse_int=str, parse_float=str, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise VaultError("Tool arguments must be complete, valid JSON before masking") from None

    decoder = json.JSONDecoder()
    values: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    while (start := arguments.find('"', pos)) != -1:
        value, end = decoder.raw_decode(arguments, start)
        assert isinstance(value, str)
        pos = end
        while pos < len(arguments) and arguments[pos] in " \t\r\n":
            pos += 1
        if pos < len(arguments) and arguments[pos] == ":":
            if masker.find_entities(value):
                raise VaultError(
                    "Tool arguments contain a sensitive JSON key; use a non-sensitive field name"
                )
        else:
            values.append(value)
            spans.append((start, end))

    # Reserve all decoded literal text together, including escaped placeholder
    # examples, so one value cannot acquire another value's existing literal token.
    masked = masker.mask_many(values)
    pieces: list[str] = []
    pos = 0
    for (start, end), original, replacement in zip(spans, values, masked, strict=True):
        if replacement != original:
            pieces.append(arguments[pos:start])
            pieces.append(json.dumps(replacement, ensure_ascii=False))
            pos = end
    pieces.append(arguments[pos:])
    return "".join(pieces)
