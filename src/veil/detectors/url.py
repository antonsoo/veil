"""URLs carrying embedded credentials or tokens.

Credential shapes, in a URL of any scheme (``https``, but also connection strings
like ``postgres://``, ``redis://`` or ``mongodb+srv://``, where credentials
are most often embedded):

- Userinfo in the authority: ``scheme://user:password@host/...``.
- A sensitive token in a query or fragment, including percent-encoded names.
- Signed storage/CDN links: AWS/GCS V4, Azure Storage SAS, and the paired
  signature/signer fields of AWS/GCS V2 and CloudFront.

The whole original URL is flagged: credentials are meaningful in context and
rewriting a signed URL can invalidate it. Recognition does not verify a signature.
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterator
from urllib.parse import unquote_plus

from veil.types import Entity, EntityType, Span

_SCHEME_START = frozenset(string.ascii_letters)
_SCHEME_CHARS = frozenset(string.ascii_letters + string.digits + "+.-")
_URL_BODY_RE = re.compile(r"[^\s\"'<>]+")
_AUTHORITY_END_RE = re.compile(r"[/\s@]")
_SENSITIVE_NAME = (
    r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|session[_-]?id)"
)
_SENSITIVE_NAME_RE = re.compile(_SENSITIVE_NAME, re.IGNORECASE)
_SENSITIVE_PARAM_RE = re.compile(r"[?&]" + _SENSITIVE_NAME + r"=[^&\s]+", re.IGNORECASE)


def _sensitive_parameters(component: str) -> bool:
    # Split before decoding, and decode names only once. An encoded '&' or '='
    # inside a value must not invent another parameter. Keep duplicate names
    # with any nonempty value; an empty later duplicate cannot hide a token.
    names = set()
    for field in component.split("&"):
        name, separator, value = field.partition("=")
        if separator and value:
            names.add(unquote_plus(name).lower())
    if any(_SENSITIVE_NAME_RE.fullmatch(name) for name in names):
        return True
    if names & {"x-amz-signature", "x-goog-signature"}:
        return True
    if {"sig", "sv"} <= names:
        return True
    return "signature" in names and bool(
        names & {"googleaccessid", "awsaccesskeyid", "key-pair-id"}
    )


def _has_credential_parameters(url: str) -> bool:
    before_fragment, _, fragment = url.partition("#")
    query = before_fragment.partition("?")[2]
    # OAuth implicit redirects use '#access_token=...'. Client-side routers
    # can use '#/callback?access_token=...'; keep those parameters together,
    # but never combine a query's signer with a fragment's signature.
    return any(
        _sensitive_parameters(component)
        for component in (query, fragment, fragment.partition("?")[2])
        if component
    )


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _has_userinfo(url: str) -> bool:
    """Does the authority carry ``user:password@``? The first ``/`` or ``@`` after the
    scheme decides: it must be an ``@``, with a ``:`` and something after it before it."""
    start = url.index("://") + 3
    end = _AUTHORITY_END_RE.search(url, start)
    return end is not None and end.group() == "@" and ":" in url[start : end.start() - 1]


def _urls(text: str) -> Iterator[tuple[int, str]]:
    """Each ``scheme://rest`` in ``text`` as (start, url), leftmost first, without overlap.

    Found from the ``://`` backwards. Matching a scheme forwards from every
    word start rescans a long run of scheme characters (``a.b.c.d...``) once
    per word in it, which takes minutes on a few hundred kilobytes.
    """
    floor = 0  # where the previous URL ended
    search = 0
    while True:
        sep = text.find("://", search)
        if sep == -1:
            return
        search = sep + 3
        run = sep
        while run > floor and text[run - 1] in _SCHEME_CHARS:
            run -= 1
        # The scheme starts at the first letter in the run that begins a word.
        start = next(
            (
                i
                for i in range(run, sep)
                if text[i] in _SCHEME_START and (i == 0 or not _is_word(text[i - 1]))
            ),
            None,
        )
        if start is None:
            continue
        body = _URL_BODY_RE.match(text, sep + 3)
        if body is None:
            continue
        yield start, text[start : body.end()]
        floor = search = body.end()


class UrlCredentialDetector:
    name = "url_credential"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for start, found in _urls(text):
            url = found.rstrip(").,;")
            # Retain legacy raw matches, including router fragments, while
            # adding decoded-name and signing-format recognition.
            if (
                _has_userinfo(url)
                or _SENSITIVE_PARAM_RE.search(url)
                or _has_credential_parameters(url)
            ):
                out.append(
                    Entity(
                        type=EntityType.URL_CREDENTIAL,
                        value=url,
                        span=Span(start, start + len(url)),
                        detector=self.name,
                    )
                )
        return out
