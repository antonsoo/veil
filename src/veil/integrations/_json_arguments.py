"""Transform decoded JSON values without rewriting surrounding argument syntax."""

from __future__ import annotations

import json

from veil._json_fields import StringToken as _StringToken
from veil._json_fields import json_string_tokens as _string_tokens
from veil.detectors.base import FieldDetector
from veil.masker import Masker
from veil.restore import restore_json_text
from veil.vault import VaultError


def mask_string_value(value: str, masker: Masker, *, key: str | None = None) -> str:
    """Retain an explicit credential field's context for its string value.

    The key stays outside the text scanned by name backends and recorded in
    the vault. Masker's request transaction, reservations and restoration
    checks apply to the original value, with no synthetic prefix to remove.
    """
    return masker.mask(value, field_name=key)


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
        tokens = _string_tokens(
            arguments,
            har_context=any(isinstance(detector, FieldDetector) for detector in masker.detectors),
        )
    except (ValueError, RecursionError):
        raise VaultError("Tool arguments must be complete, valid JSON before masking") from None
    for token in tokens:
        if token.is_key and masker.find_entities(token.value):
            raise VaultError(
                "Tool arguments contain a sensitive JSON key; use a non-sensitive field name"
            )
    values: list[tuple[_StringToken, str | None]] = []
    for token in tokens:
        if token.is_key:
            continue
        values.append((token, token.field_name))
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
        values = [
            token for token in _string_tokens(arguments, har_context=False) if not token.is_key
        ]
    except (ValueError, RecursionError):
        return restore_json_text(arguments, masker.vault)
    return _replace_values(arguments, values, [masker.restore(token.value) for token in values])
