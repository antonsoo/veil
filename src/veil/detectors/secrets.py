"""API key and secret token detector.

Two strategies, both regex/arithmetic — no network calls, no key
revocation checks:

1. **Known prefixes.** Providers stamp a recognizable prefix on issued
   keys (this is intentional on their part, to make secret scanning
   possible). We match prefix + the provider's typical trailing-character
   length/alphabet.
2. **High-entropy heuristic.** A bare base64/hex-looking token of at least
   20 characters with Shannon entropy above a threshold is flagged at low
   confidence. This will have false positives (hashes, IDs) and false
   negatives (short keys) — it's a backstop, not a guarantee.
"""

from __future__ import annotations

import math
import re

from veil.types import Entity, EntityType, Span

# (name, regex). Prefixes are real, publicly documented formats. Order
# matters: more specific/prefixed formats are matched first so the
# generic, prefix-free `aws_secret_key` pattern (any 40-char alnum run)
# never shadows a more specific match nested inside a longer token.
_KNOWN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_pat_classic", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("github_pat_fine", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b")),
    ("github_oauth", re.compile(r"\bgho_[A-Za-z0-9]{36}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,72}\b")),
    ("stripe_live_secret", re.compile(r"\bsk_live_[A-Za-z0-9]{16,99}\b")),
    ("stripe_live_restricted", re.compile(r"\brk_live_[A-Za-z0-9]{16,99}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,161}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,161}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("aws_secret_key", re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])")),
]

_HIGH_ENTROPY_RE = re.compile(r"\b[A-Za-z0-9+/_-]{20,64}\b")
_ENTROPY_THRESHOLD = 4.0


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_like_id_or_hash(s: str) -> bool:
    # Pure hex (common for hashes/UUID fragments) or a run with no digits at
    # all (likely prose/base64 padding) is not worth flagging at low confidence.
    return bool(re.fullmatch(r"[0-9a-fA-F]+", s)) or not any(ch.isdigit() for ch in s)


class SecretDetector:
    name = "secret"

    def find(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        claimed: list[Span] = []
        for pattern_name, rx in _KNOWN_PATTERNS:
            for m in rx.finditer(text):
                span = Span(m.start(), m.end())
                if any(span.overlaps(c) for c in claimed):
                    continue
                # aws_secret_key is the one pattern with no distinguishing
                # prefix (just "40 alnum characters"), so a plain SHA-1 hex
                # hash (also 40 characters) would otherwise false-positive.
                if pattern_name == "aws_secret_key" and _looks_like_id_or_hash(m.group(0)):
                    continue
                claimed.append(span)
                out.append(
                    Entity(
                        type=EntityType.SECRET,
                        value=m.group(0),
                        span=span,
                        detector=f"{self.name}:{pattern_name}",
                        confidence=0.97,
                    )
                )

        for m in _HIGH_ENTROPY_RE.finditer(text):
            span = Span(m.start(), m.end())
            if any(span.overlaps(c) for c in claimed):
                continue
            candidate = m.group(0)
            if _looks_like_id_or_hash(candidate):
                continue
            entropy = shannon_entropy(candidate)
            if entropy < _ENTROPY_THRESHOLD:
                continue
            claimed.append(span)
            out.append(
                Entity(
                    type=EntityType.SECRET,
                    value=candidate,
                    span=span,
                    detector=f"{self.name}:high_entropy",
                    confidence=min(0.6, entropy / 8),
                )
            )
        out.sort(key=lambda e: e.span.start)
        return out
