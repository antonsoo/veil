"""Restoring surrogates back to their original values.

Three entry points:

- :func:`restore_exact` — surrogate substrings must match byte-for-byte.
  Always correct, never over-restores, but a model that alters a
  surrogate (recapitalizes a fake name, adds a possessive) won't be
  caught.
- :func:`restore_tolerant` — additionally catches the rewrites models
  actually make in practice: case changes, a trailing possessive
  (``Avery Alder's`` -> ``<original>'s``), and a surrogate split across a
  line wrap. It is intentionally conservative (see the module-level
  ``_POSSESSIVE_RE`` and whitespace-collapse logic below) because a
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

import re
from dataclasses import dataclass, field

from veil.vault import Vault

_POSSESSIVE_RE = re.compile(r"^(?:'s|’s|')")


def restore_exact(text: str, vault: Vault) -> str:
    """Replace every exact surrogate occurrence with its original value."""
    r = Restorer(vault)
    return r.feed(text) + r.flush()


def restore_tolerant(text: str, vault: Vault) -> str:
    """:func:`restore_exact`, then a conservative second pass that also
    catches case changes, a trailing possessive, and a surrogate split
    across whitespace/line-break (e.g. a name wrapped mid-token by the
    model's own line width). Runs surrogates longest-first so a shorter
    surrogate that is a prefix of a longer one never shadows it.
    """
    out = restore_exact(text, vault)

    for surrogate in vault.surrogates():
        mapping = vault.lookup_surrogate(surrogate)
        if mapping is None:
            continue  # pragma: no cover - defensive
        words = surrogate.split(" ")
        # Allow arbitrary whitespace (including newlines) between the
        # surrogate's own words, and require word boundaries so we don't
        # match inside an unrelated longer word.
        body = r"\s+".join(re.escape(w) for w in words if w)
        if not body:
            continue
        pattern = re.compile(
            r"(?<!\w)" + body + r"(?!\w)(?P<poss>'s|’s|')?",
            re.IGNORECASE,
        )

        def _sub(m: re.Match[str], _original: str = mapping.original) -> str:
            suffix = m.group("poss") or ""
            return _original + suffix

        out = pattern.sub(_sub, out)
    return out


@dataclass
class _TrieNode:
    children: dict[str, _TrieNode] = field(default_factory=dict)
    terminal: str | None = None  # original value, if a surrogate ends here


def _build_trie(vault: Vault) -> _TrieNode:
    root = _TrieNode()
    for mapping in vault.mappings():
        node = root
        for ch in mapping.surrogate:
            node = node.children.setdefault(ch, _TrieNode())
        node.terminal = mapping.original
    return root


class Restorer:
    """Streaming, exact-match surrogate restorer.

    Call :meth:`feed` with each chunk as it arrives and concatenate the
    returned strings; call :meth:`flush` once at the end of the stream to
    get any text still held back. ``"".join(restorer.feed(c) for c in
    chunks) + restorer.flush()`` is guaranteed equal to
    ``restore_exact("".join(chunks), vault)`` regardless of how the text
    was split into chunks — this is what the Hypothesis property tests in
    ``tests/test_restore_streaming.py`` check.
    """

    def __init__(self, vault: Vault) -> None:
        self._trie = _build_trie(vault)
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
