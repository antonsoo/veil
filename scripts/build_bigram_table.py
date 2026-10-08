"""Build the letter-pair table in src/veil/detectors/_words.py.

    python3 scripts/build_bigram_table.py

Counts how often each letter follows each other letter inside the words and
identifiers of the Python standard library's top-level modules (code,
comments and docstrings: about a million letter pairs of English and of the
names programmers give things), and prints, for every pair, how much more or
less likely it is than a pair of letters drawn at random.

A value is 4 * ln(P(second | first) * 26), rounded and clipped to -17..18,
written as one base-36 digit (value + 17). "h" is 0, as likely as chance;
"l" is e times as likely; "d" is e times less. The table that is committed
was built with CPython 3.12.3. Another version gives a slightly different
one; the detector uses the committed table, not this script.
"""

from __future__ import annotations

import math
import re
import string
import sys
import sysconfig
from collections import Counter
from pathlib import Path

WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
DIGITS = string.digits + string.ascii_lowercase


def main() -> None:
    counts: Counter[str] = Counter()
    library = Path(sysconfig.get_paths()["stdlib"])
    for path in sorted(library.glob("*.py")):
        for word in WORD_RE.findall(path.read_text(encoding="utf-8", errors="replace")):
            lowered = word.lower()
            counts.update(a + b for a, b in zip(lowered, lowered[1:], strict=False))
    print(
        f"# CPython {sys.version.split()[0]}, {sum(counts.values()):,} letter pairs",
        file=sys.stderr,
    )
    for first in string.ascii_lowercase:
        total = sum(counts[first + second] for second in string.ascii_lowercase) + 26
        row = ""
        for second in string.ascii_lowercase:
            value = round(4 * math.log((counts[first + second] + 1) / total * 26))
            row += DIGITS[max(-17, min(18, value)) + 17]
        print(f'    "{row}",  # {first}')


if __name__ == "__main__":
    main()
