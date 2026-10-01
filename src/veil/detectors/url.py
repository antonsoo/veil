"""URLs carrying embedded credentials or tokens.

Two shapes, in a URL of any scheme (``https``, but also connection strings
like ``postgres://``, ``redis://`` or ``mongodb+srv://``, where credentials
are most often embedded):

- Userinfo in the authority: ``scheme://user:password@host/...``.
- A sensitive token in the query string, e.g. ``?api_key=...`` or
  ``?access_token=...`` — the whole URL is flagged since the token is only
  meaningful in context and query strings are easy to truncate wrong.
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterator

from veil.types import Entity, EntityType, Span

_SCHEME_START = frozenset(string.ascii_letters)
_SCHEME_CHARS = frozenset(string.ascii_letters + string.digits + "+.-")
_URL_BODY_RE = re.compile(r"[^\s\"'<>]+")
_AUTHORITY_END_RE = re.compile(r"[/\s@]")
_SENSITIVE_PARAM_RE = re.compile(
    r"[?&](?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|session[_-]?id)="
    r"[^&\s]+",
    re.IGNORECASE,
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
            if _has_userinfo(url) or _SENSITIVE_PARAM_RE.search(url):
                out.append(
                    Entity(
                        type=EntityType.URL_CREDENTIAL,
                        value=url,
                        span=Span(start, start + len(url)),
                        detector=self.name,
                    )
                )
        return out
