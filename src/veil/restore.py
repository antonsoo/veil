"""Restoring surrogates back to their original values.

Three entry points:

- :func:`restore_exact` — surrogate substrings must match byte-for-byte.
  Always correct, never over-restores, but a model that alters a
  surrogate (recapitalizes a fake name, adds a possessive) won't be
  caught.
- :func:`restore_tolerant` — additionally catches the rewrites models
  actually make in practice: case changes, a trailing possessive
  (``Avery Alder's`` -> ``<original>'s``), and a surrogate split across a
  line wrap. It is intentionally conservative (a rewritten surrogate
  must stand as a word of its own) because a
  looser tolerant match risks restoring text that was never a surrogate
  in the first place — the exact opposite of what a privacy tool should
  do. It is **not** applied inside a streaming session; streaming uses
  exact matching only (see :class:`Restorer`) since case/possessive
  rewrites cannot be verified until the trailing context has arrived.
- :class:`Restorer` — the streaming version of :func:`restore_exact`,
  built on a trie so it can emit text as soon as it is provably not part
  of any surrogate, holding back only the shortest possible-prefix
  suffix.

**Streaming, concretely.** If the vault maps ``⟨EMAIL_1⟩`` to
``alice@example.com`` and the model streams the tokens ``"...⟨EM"``,
``"AIL_1⟩ sent it"``, a naive restorer that scans each chunk in isolation
would emit ``⟨EM`` verbatim (leaking the placeholder) and then fail to
recognize ``AIL_1⟩`` as the tail of a surrogate it already partially saw.
:class:`Restorer` instead holds ``⟨EM`` back after the first chunk (it is
a valid prefix of a known surrogate) and only emits once the second chunk
completes or definitively rules out the match.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from veil.vault import Vault


def restore_exact(text: str, vault: Vault) -> str:
    """Replace every exact surrogate occurrence with its original value."""
    r = Restorer(vault)
    return r.feed(text) + r.flush()


def restore_json_text(text: str, vault: Vault) -> str:
    """:func:`restore_exact` for serialized JSON: see ``Restorer(json_string=True)``."""
    r = Restorer(vault, json_string=True)
    return r.feed(text) + r.flush()


def restore_tolerant(text: str, vault: Vault) -> str:
    """:func:`restore_exact`, plus the rewrites models make to a surrogate:
    case changes, a trailing possessive, and a surrogate split across
    whitespace or a line break (e.g. a name wrapped mid-token by the model's
    own line width). A rewritten surrogate has to stand as a word of its own
    to count (``avery alderman`` is left alone); an exact one is restored
    wherever it appears.

    One pass over ``text``: a restored value is never scanned again, so an
    original that happens to read like another value's surrogate stays as it
    is.
    """
    exact = _trie(vault, json_string=False)
    loose = _loose_trie(vault)
    out: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        ch = text[pos]
        hit = _longest_exact(exact, text, pos) if ch in exact.children else None
        if hit is None and ch.casefold() in loose.children and not _mid_word(text, pos):
            hit = _longest_loose(loose, text, pos)
        if hit is None:
            out.append(ch)
            pos += 1
        else:
            pos, original = hit
            out.append(original)
    return "".join(out)


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _mid_word(text: str, pos: int) -> bool:
    """Would a match starting or ending at ``pos`` cut a word in two? ``avery alderman``
    is not ``Avery Alder``; a bracketed placeholder is delimited whatever it touches."""
    return 0 < pos < len(text) and _is_word(text[pos - 1]) and _is_word(text[pos])


@dataclass
class _TrieNode:
    children: dict[str, _TrieNode] = field(default_factory=dict)
    terminal: str | None = None  # original value, if a surrogate ends here


def _json_escaped(value: str, *, ascii_only: bool) -> str:
    """``value`` as it appears between the quotes of a JSON string literal."""
    return json.dumps(value, ensure_ascii=ascii_only)[1:-1]


def _build_trie(vault: Vault, *, json_string: bool = False) -> _TrieNode:
    root = _TrieNode()

    def add(surrogate: str, original: str) -> None:
        node = root
        for ch in surrogate:
            node = node.children.setdefault(ch, _TrieNode())
        node.terminal = original

    for mapping in vault.mappings():
        if not json_string:
            add(mapping.surrogate, mapping.original)
            continue
        # Inside a JSON string the original must be escaped to keep the JSON valid, and the model
        # may have written the surrogate with its non-ASCII characters as \uXXXX escapes.
        original = _json_escaped(mapping.original, ascii_only=False)
        add(mapping.surrogate, original)
        add(_json_escaped(mapping.surrogate, ascii_only=True), original)
    return root


def _trie(vault: Vault, *, json_string: bool) -> _TrieNode:
    """The vault's surrogate trie, built once per vault state rather than per string restored."""
    key = "json_trie" if json_string else "trie"
    trie = vault._derived.get(key)
    if trie is None:
        trie = vault._derived[key] = _build_trie(vault, json_string=json_string)
    return trie


def _loose_trie(vault: Vault) -> _TrieNode:
    """Surrogates as :func:`restore_tolerant` matches them: case-folded, with the
    spaces between a surrogate's words standing for any run of whitespace."""
    trie = vault._derived.get("loose_trie")
    if trie is None:
        trie = _TrieNode()
        for surrogate in vault.surrogates():  # longest first: it wins a tie on the folded form
            mapping = vault.lookup_surrogate(surrogate)
            words = [w for w in surrogate.split(" ") if w]
            if mapping is None or not words:
                continue
            node = trie
            for ch in " ".join(words):
                node = node.children.setdefault(ch if ch == " " else ch.casefold(), _TrieNode())
            if node.terminal is None:
                node.terminal = mapping.original
        vault._derived["loose_trie"] = trie
    return trie


def _longest_exact(trie: _TrieNode, text: str, pos: int) -> tuple[int, str] | None:
    """The longest surrogate starting at ``pos``, as (end, original)."""
    node = trie
    best: tuple[int, str] | None = None
    for i in range(pos, len(text)):
        nxt = node.children.get(text[i])
        if nxt is None:
            break
        node = nxt
        if node.terminal is not None:
            best = (i + 1, node.terminal)
    return best


def _longest_loose(trie: _TrieNode, text: str, pos: int) -> tuple[int, str] | None:
    """The longest rewritten surrogate starting at ``pos`` and ending at a word boundary."""
    node = trie
    best: tuple[int, str] | None = None
    i = pos
    n = len(text)
    while i < n:
        ch = text[i]
        gap = node.children.get(" ") if ch.isspace() else None
        if gap is not None:
            while i < n and text[i].isspace():
                i += 1
            node = gap
            continue
        nxt = node.children.get(ch.casefold())
        if nxt is None:
            break
        node = nxt
        i += 1
        if node.terminal is not None and not _mid_word(text, i):
            best = (i, node.terminal)
    return best


class Restorer:
    """Streaming, exact-match surrogate restorer.

    Call :meth:`feed` with each chunk as it arrives and concatenate the
    returned strings; call :meth:`flush` once at the end of the stream to
    get any text still held back. ``"".join(restorer.feed(c) for c in
    chunks) + restorer.flush()`` is guaranteed equal to
    ``restore_exact("".join(chunks), vault)`` regardless of how the text
    was split into chunks — this is what the Hypothesis property tests in
    ``tests/test_restore_streaming.py`` check.

    With ``json_string=True`` the text is (a fragment of) serialized JSON,
    such as a tool call's streamed arguments: a surrogate is also recognized
    in its ``\\uXXXX``-escaped form, and originals are written JSON-escaped
    so the arguments stay valid JSON.
    """

    def __init__(self, vault: Vault, *, json_string: bool = False) -> None:
        self._trie = _trie(vault, json_string=json_string)
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        emitted, self._buffer = self._consume(self._buffer, final=False)
        return emitted

    def flush(self) -> str:
        emitted, remainder = self._consume(self._buffer, final=True)
        self._buffer = ""
        assert remainder == ""  # a final pass never holds anything back
        return emitted

    def _consume(self, buffer: str, *, final: bool) -> tuple[str, str]:
        out: list[str] = []
        pos = 0
        n = len(buffer)
        while pos < n:
            node = self._trie
            i = pos
            best_end: int | None = None
            best_original: str | None = None
            broke = False
            while i < n:
                nxt = node.children.get(buffer[i])
                if nxt is None:
                    broke = True
                    break
                node = nxt
                i += 1
                if node.terminal is not None:
                    best_end = i
                    best_original = node.terminal
            if not final and not broke and i == n and node.children:
                # Ran out of buffer mid-prefix; more input could still
                # complete a (possibly longer) surrogate. Hold this tail.
                break
            if best_end is not None:
                out.append(best_original or "")
                pos = best_end
                continue
            # No surrogate can start at `pos` no matter what follows.
            out.append(buffer[pos])
            pos += 1
        return "".join(out), buffer[pos:]
