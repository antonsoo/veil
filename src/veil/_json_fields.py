"""String positions and original field context in complete JSON documents.

Numbers are validated without conversion. Object pairs retain duplicates; only
the HAR fields used to establish HTTP header context must be unambiguous. No parsed
tree is serialized back over the caller's source text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from email import policy
from email.errors import MessageError
from email.message import EmailMessage
from email.parser import Parser
from email.policy import Policy
from urllib.parse import parse_qsl, urlsplit

from veil.detectors._credential_fields import is_credential_field
from veil.vault import VaultError


@dataclass(frozen=True)
class StringToken:
    start: int
    end: int
    value: str
    is_key: bool
    field_name: str | None = None
    har_credential: bool = False


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
            "HAR HTTP context contains a duplicate routing field; use unambiguous header/cookie records"
        )
    return matches[0] if matches else (-1, _MISSING)


def _reject_constant(_value: str) -> None:
    raise ValueError("Non-JSON numeric constant")


def _encoded_credential_name(text: str) -> str | None:
    try:
        pairs = parse_qsl(text, keep_blank_values=True, max_num_fields=10000)
    except ValueError:
        raise VaultError("HAR form/query data exceeds the 10,000-field inspection limit") from None
    return next((name for name, value in pairs if value and is_credential_field(name)), None)


def _form_credential_name(mime_type: str, text: str) -> str | None:
    if "\r" in mime_type or "\n" in mime_type:
        raise VaultError("HAR form content type cannot contain line breaks")
    media_type = mime_type.split(";", 1)[0].strip().lower()
    if media_type == "application/x-www-form-urlencoded":
        return _encoded_credential_name(text)
    if media_type != "multipart/form-data":
        return None
    # Use the native MIME parser to read field names, never to rewrite the
    # source body. A credential-bearing serialized form stays opaque, including
    # MIME escaping, transfer encodings and values spanning physical lines.
    created = 0

    class BoundedMessage(EmailMessage):
        def __init__(self, policy: Policy = policy.default) -> None:
            nonlocal created
            created += 1
            if created > 10000:
                raise VaultError("HAR multipart form exceeds the 10,000-part inspection limit")
            super().__init__(policy=policy)

    try:
        message = Parser(_class=BoundedMessage, policy=policy.default).parsestr(
            f"Content-Type: {mime_type}\r\nMIME-Version: 1.0\r\n\r\n{text}"
        )
        if not message.is_multipart():
            raise VaultError("HAR multipart form has no usable boundary")
        credential = None
        for index, part in enumerate(message.walk()):
            if index >= 10000:
                raise VaultError("HAR multipart form exceeds the 10,000-part inspection limit")
            if part.defects or any(getattr(value, "defects", ()) for _, value in part.items()):
                raise VaultError("HAR multipart form is incomplete or ambiguous")
            if any(
                len(part.get_all(header, [])) > 1
                for header in ("content-disposition", "content-type", "content-transfer-encoding")
            ):
                raise VaultError("HAR multipart form has ambiguous routing headers")
            name = part.get_param("name", header="content-disposition")
            if isinstance(name, str) and is_credential_field(name) and part.get_payload():
                credential = name
        return credential
    except (ValueError, RecursionError, MessageError):
        raise VaultError("HAR multipart form cannot be inspected safely") from None


def har_field_contexts(root: object) -> dict[tuple[int, ...], str]:
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

    def records(
        message: _Object | dict[str, object], path: tuple[int, ...], kind: str
    ) -> str | None:
        kind_index, values = _one(message, kind)
        if values is _MISSING:
            return None
        if not isinstance(values, (list, tuple)):
            raise VaultError("HAR HTTP field records must be arrays before masking")
        credential = None
        for item_index, item in enumerate(values):
            if not isinstance(item, (_Object, dict)):
                raise VaultError("HAR HTTP field records must be objects before masking")
            _, name = _one(item, "name")
            value_index, value = _one(item, "value")
            if not isinstance(name, str) or (
                not isinstance(value, str) and not (kind == "params" and value is _MISSING)
            ):
                raise VaultError("HAR HTTP field records need unambiguous string names and values")
            secret = is_credential_field(name)
            if secret and isinstance(value, str) and value:
                credential = name
            if isinstance(value, str) and (
                secret
                or kind == "cookies"
                or (
                    kind == "headers"
                    and name.lower()
                    in {"cookie", "set-cookie", "authorization", "proxy-authorization"}
                )
            ):
                fields[(*path, kind_index, item_index, value_index)] = (
                    "Cookie" if kind == "cookies" else name
                )
        return credential

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
                    "HAR 1.2 entries must be an array before HTTP context can be masked"
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
                            "HAR requests/responses must be objects before HTTP context can be masked"
                        )
                    path = (*candidate_path, log_index, entries_index, entry_index, side_index)
                    records(message, path, "headers")
                    records(message, path, "cookies")
                    if side != "request":
                        continue
                    query_credential = records(message, path, "queryString")
                    url_index, url = _one(message, "url")
                    if isinstance(url, str):
                        try:
                            query_credential = query_credential or _encoded_credential_name(
                                urlsplit(url).query
                            )
                        except ValueError:
                            raise VaultError("HAR request URL cannot be inspected safely") from None
                        if query_credential:
                            fields[(*path, url_index)] = query_credential
                    post_index, post = _one(message, "postData")
                    if post is _MISSING:
                        continue
                    if not isinstance(post, (_Object, dict)):
                        raise VaultError("HAR postData must be an object before masking")
                    post_path = (*path, post_index)
                    form_credential = records(post, post_path, "params")
                    _, mime_type = _one(post, "mimeType")
                    text_index, text = _one(post, "text")
                    if isinstance(text, str) and text:
                        if isinstance(mime_type, str):
                            # Inspect MIME even when params supply a credential:
                            # contradictory/incomplete framing cannot pass silently.
                            form_credential = (
                                _form_credential_name(mime_type, text) or form_credential
                            )
                        if form_credential:
                            fields[(*post_path, text_index)] = form_credential
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
        tokens[cursor] = replace(token, field_name=field)
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

    for path, field_name in har_field_contexts(root).items():
        index = positions[path]
        tokens[index] = replace(
            tokens[index], field_name=field_name, har_credential=is_credential_field(field_name)
        )
    return tokens


def string_source_span(text: str, token: StringToken, start: int, end: int) -> tuple[int, int]:
    """Map a decoded substring back to its spelling in a validated JSON string.

    Only walk as far as the selected end. Escape pairs representing one Unicode
    scalar occupy one decoded position, just as Python's JSON decoder reports.
    The caller can then replace source bytes without re-encoding adjacent text.
    """
    pos = token.start + 1
    source_start = pos
    for index in range(end):
        if index == start:
            source_start = pos
        if text[pos] == "\\":
            if text[pos + 1] == "u":
                unit = int(text[pos + 2 : pos + 6], 16)
                pos += 6
                if (
                    0xD800 <= unit <= 0xDBFF
                    and text[pos : pos + 2] == r"\u"
                    and 0xDC00 <= int(text[pos + 2 : pos + 6], 16) <= 0xDFFF
                ):
                    pos += 6
            else:
                pos += 2
        else:
            pos += 1
    return source_start, pos
