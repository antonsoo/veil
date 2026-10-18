"""String positions and original field context in complete JSON documents.

Numbers are validated without conversion. Object pairs retain duplicates; only
the HAR fields used to establish cookie context must be unambiguous. No parsed
tree is serialized back over the caller's source text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from veil.vault import VaultError


@dataclass(frozen=True)
class StringToken:
    start: int
    end: int
    value: str
    is_key: bool
    field_name: str | None = None
    cookie_context: bool = False


@dataclass
class _Object:
    pairs: list[tuple[str, object]]


_MISSING = object()


def _pairs(node: _Object | dict[str, object]) -> list[tuple[str, object]]:
    return node.pairs if isinstance(node, _Object) else list(node.items())


def _one(node: _Object | dict[str, object], key: str) -> tuple[int, object]:
    matches = [(i, value) for i, (name, value) in enumerate(_pairs(node)) if name == key]
    if len(matches) > 1:
        # Keys and values can be private; don't quote either in diagnostics.
        raise VaultError(
            "HAR cookie context contains a duplicate routing field; use unambiguous header/cookie records"
        )
    return matches[0] if matches else (-1, _MISSING)


def _reject_constant(_value: str) -> None:
    raise ValueError("Non-JSON numeric constant")


def har_cookie_fields(root: object) -> dict[tuple[int, ...], str]:
    objects: list[tuple[_Object | dict[str, object], tuple[int, ...]]] = []
    fields: dict[tuple[int, ...], str] = {}
    active: set[int] = set()

    def walk(value: object, path: tuple[int, ...]) -> None:
        if not isinstance(value, (_Object, dict, list, tuple)):
            return
        if id(value) in active:
            raise VaultError("Tool input JSON trees cannot contain cycles")
        active.add(id(value))
        try:
            if isinstance(value, (_Object, dict)):
                objects.append((value, path))
                for i, (_key, child) in enumerate(_pairs(value)):
                    walk(child, (*path, i))
            else:
                for i, child in enumerate(value):
                    walk(child, (*path, i))
        finally:
            active.remove(id(value))

    walk(root, ())

    def records(message: _Object | dict[str, object], path: tuple[int, ...], kind: str) -> None:
        kind_index, values = _one(message, kind)
        if values is _MISSING:
            return
        if not isinstance(values, (list, tuple)):
            raise VaultError(
                "HAR headers/cookies must be arrays before cookie context can be masked"
            )
        for item_index, item in enumerate(values):
            if not isinstance(item, (_Object, dict)):
                raise VaultError("HAR header/cookie records must be objects before masking")
            _, name = _one(item, "name")
            value_index, value = _one(item, "value")
            if not isinstance(name, str) or not isinstance(value, str):
                raise VaultError(
                    "HAR header/cookie records need unambiguous string names and values"
                )
            if kind == "cookies" or name.lower() in {"cookie", "set-cookie"}:
                fields[(*path, kind_index, item_index, value_index)] = (
                    name if kind == "headers" else "Cookie"
                )

    for candidate, candidate_path in objects:
        for log_index, (key, log) in enumerate(_pairs(candidate)):
            if key != "log" or not isinstance(log, (_Object, dict)):
                continue
            if not any(key == "version" and value == "1.2" for key, value in _pairs(log)):
                continue
            _one(candidate, "log")
            _one(log, "version")
            entries_index, entries = _one(log, "entries")
            if not isinstance(entries, (list, tuple)):
                raise VaultError(
                    "HAR 1.2 entries must be an array before cookie context can be masked"
                )
            for entry_index, entry in enumerate(entries):
                if not isinstance(entry, (_Object, dict)):
                    raise VaultError("HAR 1.2 entries must contain objects before masking")
                for side in ("request", "response"):
                    side_index, message = _one(entry, side)
                    if message is _MISSING:
                        continue
                    if not isinstance(message, (_Object, dict)):
                        raise VaultError(
                            "HAR requests/responses must be objects before cookie context can be masked"
                        )
                    path = (*candidate_path, log_index, entries_index, entry_index, side_index)
                    records(message, path, "headers")
                    records(message, path, "cookies")
    return fields


def json_string_tokens(text: str, *, har_context: bool = True) -> list[StringToken]:
    root: object = json.loads(
        text,
        object_pairs_hook=_Object,
        parse_int=lambda _: None,
        parse_float=lambda _: None,
        parse_constant=_reject_constant,
    )
    decoder = json.JSONDecoder()
    tokens: list[StringToken] = []
    pos = 0
    while (start := text.find('"', pos)) != -1:
        value, end = decoder.raw_decode(text, start)
        assert isinstance(value, str)
        pos = end
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        tokens.append(StringToken(start, end, value, pos < len(text) and text[pos] == ":"))

    cursor = 0
    positions: dict[tuple[int, ...], int] = {}

    def consume(value: str, key: bool, field: str | None = None) -> None:
        nonlocal cursor
        token = tokens[cursor]
        assert token.value == value and token.is_key == key
        cookie = not key and field is not None and field.lower() in {"cookie", "set-cookie"}
        tokens[cursor] = replace(token, field_name=field, cookie_context=cookie)
        cursor += 1

    def walk(value: object, path: tuple[int, ...], field: str | None = None) -> None:
        if isinstance(value, str):
            positions[path] = cursor
            consume(value, False, field)
        elif isinstance(value, _Object):
            for index, (key, child) in enumerate(value.pairs):
                consume(key, True)
                walk(child, (*path, index), key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*path, index))

    walk(root, ())
    assert cursor == len(tokens)
    if not har_context:
        return tokens

    for path, field_name in har_cookie_fields(root).items():
        index = positions[path]
        tokens[index] = replace(tokens[index], field_name=field_name, cookie_context=True)
    return tokens
