"""Compare reservation availability against direct normalized substring lookup.

The reference scans all sources; it has no character index. Interleave new
sources and checks to exercise late nested reservations as well as preloaded
batches. This is a reservation invariant, not a detector accuracy measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
args = parser.parse_args()
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

from veil.masker import _MaskingBatch  # noqa: E402

seed = 20261013
rng = random.Random(seed)
alphabet = "abcXYZßΣςé⟨⟩[]_123 \t\n\u00a0"
results = []
for _ in range(200):
    batch = _MaskingBatch()
    sources = []
    for index in range(100):
        if index % 4 == 0:
            source = "".join(rng.choices(alphabet, k=rng.randrange(60)))
            sources.append(" ".join(source.split()).casefold())
            batch.reserve(source)
        candidate = "".join(rng.choices(alphabet, k=rng.randrange(12)))
        if index % 7 == 0 and sources:
            candidate = rng.choice(sources)[: rng.randrange(10)]
        normalized = " ".join(candidate.split()).casefold()
        if index % 11 == 0:
            batch.originals.add(normalized)
        expected = (
            bool(normalized)
            and normalized not in batch.originals
            and all(normalized not in source for source in sources)
        )
        actual = batch.available(candidate)
        assert actual == expected, (sources, candidate, expected, actual)
        results.append([index, sources.copy(), candidate, expected, actual])
print(
    json.dumps(
        {
            "seed": seed,
            "checks": len(results),
            "disagreements": 0,
            "sha256": hashlib.sha256(json.dumps(results, ensure_ascii=False).encode()).hexdigest(),
        },
        indent=2,
    )
)
