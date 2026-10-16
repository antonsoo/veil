"""Bounded local detector timings, including malformed input; no latency guarantee."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from veil.detectors.secrets import SecretDetector

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
rows = []
detector = SecretDetector()
for size in (10_000, 100_000, 1_000_000):
    for name, source in (
        ("quoted", 'password="' + "river " * (size // 6) + '"\n'),
        ("escaped-quotes", 'password="' + 'a\\"' * (size // 3) + '"\n'),
        ("unclosed-quoted", 'password="' + "a" * size + "\n"),
        ("bare", "API_KEY=" + "a" * size + "\n"),
        ("repeated", "password=short\n" * (size // 15)),
        ("missing", "password:\n" * (size // 10)),
        ("uppercase-prefix", "A" * size + "_NOT_A_CREDENTIAL=plain\n"),
        ("ordinary-prose", "A password reset can resolve a problem.\n" * (size // 39)),
    ):
        detector.find(source)
        timings = []
        for _ in range(3):
            started = time.perf_counter()
            found = detector.find(source)
            timings.append(time.perf_counter() - started)
        rows.append(
            {
                "case": name,
                "sizeParameter": size,
                "bytes": len(source.encode()),
                "sourceSha256": hashlib.sha256(source.encode()).hexdigest(),
                "detections": len(found),
                "medianSeconds": statistics.median(timings),
                "seconds": timings,
            }
        )
report = {
    "scope": __doc__,
    "python": platform.python_version(),
    "platform": platform.platform(),
    "warmups": 1,
    "repeats": 3,
    "rows": rows,
}
args.output.write_text(json.dumps(report, indent=2) + "\n")
print(f"{len(rows)} measured cases; maximum median {max(r['medianSeconds'] for r in rows):.3f}s")
