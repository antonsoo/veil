"""Complete mailbox detection in prose, without DNS or deliverability checks.

Recognize ASCII dot-atoms, letter/mark/number international local parts,
quoted local parts and DNS-shaped Unicode/ASCII domains. Candidates are
bounded around each @, so invalid long tokens cannot become suffix matches
or make a regex retry an arbitrarily long prefix. Original spelling and
offsets are retained; IDNA encoding is only a structural domain check.

This is not a full RFC 5322 parser: comments, folded whitespace, domain
literals and local-only domains are outside this detector's scope.
"""

from __future__ import annotations

import re
import string
import unicodedata
from collections.abc import Iterator

from veil.types import Entity, EntityType, Span

# RFC 5322 section 3.2.3, including punctuation that the old regex skipped.
_ATEXT = frozenset(string.ascii_letters + string.digits + "!#$%&'*+-/=?^_`{|}~")
_DNS_LABEL_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_QUOTED_RE = re.compile(r'"(?:[\x20-\x21\x23-\x5b\x5d-\x7e]|\\[\x20-\x7e]|[^\x00-\x7f]){0,64}"')
_URI_START_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


def _atom_char(char: str) -> bool:
    return char in _ATEXT or (not char.isascii() and unicodedata.category(char)[0] in "LMN")


def _domain_char(char: str) -> bool:
    # Include invalid '_'/'+' and format characters in the candidate so they
    # cannot leave an apparently valid, shorter domain in front of them.
    return (
        char.isalnum()
        or char in ".-_+"
        or (not char.isascii() and unicodedata.category(char)[0] in "MC")
    )


def _fits_local(local: str) -> bool:
    try:
        return len(local.encode("utf-8")) <= 64
    except UnicodeEncodeError:
        return False


def _local_start(text: str, at: int, floor: int) -> int | None:
    if at == floor:
        return None
    lower = max(floor, at - 64)
    if text[at - 1] == '"':
        for start in range(lower, at - 1):
            if text[start] == '"' and _QUOTED_RE.fullmatch(text, start, at):
                local = text[start:at]
                if any(not ch.isascii() and unicodedata.category(ch)[0] == "C" for ch in local):
                    return None
                if start > floor and (_atom_char(text[start - 1]) or text[start - 1] in ".\\"):
                    return None
                return start if _fits_local(local) else None
        return None
    start = at
    while start > lower and (_atom_char(text[start - 1]) or text[start - 1] == "."):
        start -= 1
    # A length limit must reject the whole token, never select its last bytes.
    if start > floor and (_atom_char(text[start - 1]) or text[start - 1] == "."):
        return None
    # Unsupported invisible/symbol local characters must not expose a prefix
    # by letting a suffix look like a new address.
    if (
        start > floor
        and not text[start - 1].isascii()
        and (not text[start - 1].isspace() and unicodedata.category(text[start - 1])[0] in "CS")
    ):
        return None
    local = text[start:at]
    if not local or local.startswith(".") or local.endswith(".") or ".." in local:
        return None
    # Empty prose/code quoting is not an identity: ``@app.route`` would
    # otherwise become a mailbox whose local part consists only of backticks.
    if not local.strip("'`"):
        return None
    if (
        start > floor + 1
        and text[start - 1] == "@"
        and (_atom_char(text[start - 2]) or text[start - 2] == ".")
    ):
        return None
    return start if _fits_local(local) else None


def _quoted_local_parts(text: str) -> Iterator[tuple[int, int]]:
    # Only a closing quote followed by @ can terminate this local-part form.
    # Starting a bounded regex at every quote still wastes substantial time
    # on escaped-quote logs, most of which contain no mailbox at all.
    for match in re.finditer('"@', text):
        at = match.start() + 1
        start = _local_start(text, at, 0)
        if start is not None:
            yield start, at


def _valid_domain(domain: str) -> bool:
    labels = domain.split(".")
    if len(labels) < 2 or any(not label for label in labels):
        return False
    encoded = []
    for label in labels:
        if any(
            not (char.isalnum() or char == "-" or unicodedata.category(char)[0] == "M")
            for char in label
        ):
            return False
        try:
            ascii_label = label.encode("idna").decode("ascii")
            if not _DNS_LABEL_RE.fullmatch(ascii_label):
                return False
            if ascii_label.lower().startswith("xn--"):
                # The codec does not validate already-ASCII A-labels on encode.
                ascii_label.encode("ascii").decode("idna")
        except UnicodeError:
            return False
        encoded.append(ascii_label)
    if len(".".join(encoded)) > 253:
        return False
    tld = encoded[-1]
    return tld.lower().startswith("xn--") or (len(tld) >= 2 and tld.isalpha())


class EmailDetector:
    name = "email"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        floor = 0
        quoted = _quoted_local_parts(text)
        quote = next(quoted, None)
        for match in re.finditer("@", text):
            at = match.start()
            if at < floor:
                continue
            while quote is not None and at > quote[1]:
                quote = next(quoted, None)
            # An @ inside a quoted local part is text, not the separator.
            if quote is not None and quote[0] < at < quote[1]:
                continue
            start = _local_start(text, at, floor)
            if start is None:
                continue
            end = at + 1
            limit = min(len(text), end + 254)
            while end < limit and _domain_char(text[end]):
                end += 1
            if end < len(text) and _domain_char(text[end]):
                continue
            # Calendar account logs can separate an email from its service
            # URL with @. Retain that contact, but reject two joined mailboxes.
            if end < len(text) and text[end] == "@" and not _URI_START_RE.match(text, end + 1):
                continue
            # A sentence's trailing full stop is outside the mailbox.
            end = at + 1 + len(text[at + 1 : end].rstrip("."))
            if not _valid_domain(text[at + 1 : end]):
                continue
            # Single quotes/backticks around an address are prose delimiters;
            # an apostrophe inside a local part retains its mailbox meaning.
            if end < len(text) and text[end] in "'`" and text[start] == text[end]:
                start += 1
            if start == at:
                continue
            value = text[start:end]
            out.append(
                Entity(
                    type=EntityType.EMAIL, value=value, span=Span(start, end), detector=self.name
                )
            )
            floor = end
        return out
