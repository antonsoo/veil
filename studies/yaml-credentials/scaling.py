"""Bounded raw detector measurements; includes repeated header comments."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from veil.detectors import _credential_fields
from veil.detectors.secrets import SecretDetector

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
detector = SecretDetector()
rows = []
for count in (100, 1_000, 10_000):
    for name, source in (
        ("literal-blocks", "password: |-\n  river\n  stone\nmode: read-only\n" * count),
        ("folded-blocks", "client_secret: >2-\n  river\n  stone\nmode: read-only\n" * count),
        ("empty-blocks", "password: |\n\nstatus: ready\n" * count),
        (
            "assignment-comments",
            "password: | # " + "password: | # " * count + "api_key=short\n  river\n  stone\n",
        ),
        ("bare-pipes", "password=river|stone\n" * count),
    ):
        detector.find(source)
        seconds = []
        for _ in range(3):
            start = time.perf_counter()
            found = detector.find(source)
            seconds.append(time.perf_counter() - start)
        rows.append(
            {
                "case": name,
                "repetitions": count,
                "bytes": len(source.encode()),
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "detections": len(found),
                "seconds": seconds,
                "median_seconds": statistics.median(seconds),
            }
        )
result = {
    "scope": __doc__,
    "python": platform.python_version(),
    "platform": platform.platform(),
    "runtime_sha256": hashlib.sha256(Path(_credential_fields.__file__).read_bytes()).hexdigest(),
    "warmups": 1,
    "repeats": 3,
    "rows": rows,
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2) + "\n")
print(f"{len(rows)} cases; maximum median {max(row['median_seconds'] for row in rows):.3f}s")
