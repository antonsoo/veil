"""Property tests over generated text: masking is reversible, and the linear
scanners in the URL and secret detectors find what the plain regular
expressions they replaced would find.
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from veil.backends.known_entities import KnownEntitiesBackend
from veil.detectors import all_detectors
from veil.detectors.secrets import _private_key_blocks
from veil.detectors.url import _has_userinfo, _urls
from veil.masker import Masker
from veil.surrogates import RealisticSurrogates

_DASHES = "-" * 5


def _pem_line(edge: str, label: str) -> str:
    return f"{_DASHES}{edge} {label}PRIVATE KEY{_DASHES}"


# Values of every type the detectors know, fragments that nearly match, and glue.
_TOKENS = [
    "alice@example.com", "bob.smith+tag@mail.co.uk", "o'neil@pub.ie", "x@", "@",
    "https://user:pw@host.example/path", "postgres://app:s3cret@db:5432/x",
    "http://a.b/c?token=abc123&x=1", "https://example.com/plain", "://", "x://", "a.b.c://d",
    "_x://y:z@h", "é://u:p@h", "1x://u:p@h", "s3+http://k:v@h/", "x://y://u:p@h", "(https://u:p@h/a).",
    _pem_line("BEGIN", ""), _pem_line("END", ""), _pem_line("BEGIN", "RSA "), _pem_line("END", "RSA "),
    _DASHES, f"{_DASHES}BEGIN ", f"{_DASHES}END ", "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC", "Proc-Type: 4,ENCRYPTED",
    "AKIAIOSFODNN7EXAMPLE", "q7Rz2LmN8vXc4KpT9wYb3HdJ6sGf", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    "born", "DOB", "03/14/1990", "1990-03-14", "March 14, 1990",
    "415-555-2671", "+1 (415) 555-2671", "+442071838750", "order", "#", "555-2671",
    "10.0.0.1", "v1.2.3.4", "version", "2001:db8::1", "::1", "999.1.1.1",
    "123-45-6789", "078 05 1120", "ssn", "123456789", "4111 1111 1111 1111", "5500-0000-0000-0004",
    "DE89 3704 0044 0532 0130 00", "GB82WEST12345698765432", "12 Main Street", "742 Evergreen Terrace, Apt 2",
    "Alice Johnson", "alice johnson", "Acme Corp", "Springfield", "Alice",
    " ", " ", "\n", "\t", ".", ",", ";", ":", "/", "-", "_", "'s", "(", ")", "<", ">", '"', "é", "x", "A", "1", "=", "&", "?", "+",
]  # fmt: skip
_text = st.lists(st.sampled_from(_TOKENS), max_size=40).map("".join)


def _masker(*, realistic: bool) -> Masker:
    backend = KnownEntitiesBackend(
        persons=["Alice Johnson", "Alice"], orgs=["Acme Corp"], locations=["Springfield"]
    )
    if realistic:
        return Masker(
            detectors=all_detectors(),
            name_backends=[backend],
            surrogate_generator=RealisticSurrogates(),
        )
    return Masker(detectors=all_detectors(), name_backends=[backend])


@settings(max_examples=400, deadline=None)
@given(_text, st.booleans())
def test_mask_then_restore_gives_the_text_back(text: str, realistic: bool) -> None:
    masker = _masker(realistic=realistic)
    entities = masker.find_entities(text)
    assert all(a.span.end <= b.span.start for a, b in zip(entities, entities[1:], strict=False))
    masked = masker.mask(text)
    assert masker.restore(masked, tolerant=False) == text
    assert masker.restore(masked) == text
    for entity in entities:
        assert text[entity.span.start : entity.span.end] == entity.value


@settings(max_examples=400, deadline=None)
@given(_text)
def test_masking_twice_with_one_vault_reuses_every_surrogate(text: str) -> None:
    masker = _masker(realistic=False)
    first = masker.mask(text)
    size = len(masker.vault)
    assert masker.mask(text) == first
    assert len(masker.vault) == size


# What the detectors used before: correct, but quadratic on long repetitive input.
_URL_REFERENCE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.IGNORECASE)
_PEM_REFERENCE = re.compile(
    rf"{_DASHES}BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?){_DASHES}"
    rf"(?:[\s\S]*?{_DASHES}END \1{_DASHES}|[A-Za-z0-9+/=:,\s-]*)"
)


@settings(max_examples=600, deadline=None)
@given(_text)
def test_url_scanner_matches_the_reference_expression(text: str) -> None:
    assert list(_urls(text)) == [(m.start(), m.group(0)) for m in _URL_REFERENCE.finditer(text)]


_USERINFO_REFERENCE = re.compile(r"^[a-z][a-z0-9+.-]*://[^/\s@]*:[^/\s@]+@", re.IGNORECASE)
_authority = st.lists(st.sampled_from(["u", ":", "@", "/", "p", "?", "h", ".", "#"]), max_size=12)


@settings(max_examples=600, deadline=None)
@given(_authority.map("".join))
def test_userinfo_check_matches_the_reference_expression(rest: str) -> None:
    url = "db+x://" + rest
    assert _has_userinfo(url) == bool(_USERINFO_REFERENCE.search(url))


@settings(max_examples=600, deadline=None)
@given(_text)
def test_private_key_scanner_matches_the_reference_expression(text: str) -> None:
    assert list(_private_key_blocks(text)) == [m.span() for m in _PEM_REFERENCE.finditer(text)]
