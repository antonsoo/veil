"""URLs carrying embedded credentials or tokens.

Two shapes:

- Userinfo in the authority: ``scheme://user:password@host/...``.
- A sensitive token in the query string, e.g. ``?api_key=...`` or
  ``?access_token=...`` — the whole URL is flagged since the token is only
  meaningful in context and query strings are easy to truncate wrong.
"""

from __future__ import annotations

import re

from veil.types import Entity, EntityType, Span

_URL_RE = re.compile(r"\bhttps?://[^\s\"'<>]+", re.IGNORECASE)
_USERINFO_RE = re.compile(r"^https?://[^/\s@]+:[^/\s@]+@")
_SENSITIVE_PARAM_RE = re.compile(
    r"[?&](?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|session[_-]?id)="
    r"[^&\s]+",
    re.IGNORECASE,
)


class UrlCredentialDetector:
    name = "url_credential"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _URL_RE.finditer(text):
            url = m.group(0).rstrip(").,;")
            if _USERINFO_RE.search(url) or _SENSITIVE_PARAM_RE.search(url):
                end = m.start() + len(url)
                out.append(
                    Entity(
                        type=EntityType.URL_CREDENTIAL,
                        value=url,
                        span=Span(m.start(), end),
                        detector=self.name,
                    )
                )
        return out
