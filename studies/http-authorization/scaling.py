"""Controlled detector timings; not production latency or a complexity proof."""

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
        ("large-opaque-credential", "Authorization: Basic " + "a" * size + "/+==\n"),
        ("ordinary-prose", "Basic algebra and bearer of good news.\n" * (size // 40)),
        ("repeated-headers", "Authorization: Bearer abc\r\n" * (size // 30)),
        ("empty-scheme", "Authorization:" + " " * size + "\n"),
        ("glued-unsupported", "Authorization: Bearer " + "a" * size + "=invalid\n"),
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
    "python": platform.python_version(),
    "platform": platform.platform(),
    "warmups": 1,
    "repeats": 3,
    "rows": rows,
}
args.output.write_text(json.dumps(report, indent=2) + "\n")
print(
    f"{len(rows)} measured cases, largest median {max(row['medianSeconds'] for row in rows):.3f} s"
)
