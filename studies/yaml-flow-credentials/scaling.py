"""Measure repeated quoted values and malformed tails; no worst-case guarantee."""

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
        ("apostrophes", "password: 'sun''rise'\nmode: read-only\n" * count),
        ("wrapped", 'client_secret: "river\\\n  stone"\nmode: read-only\n' * count),
        ("plain", "password: river stone\n  quiet meadow\nmode: read-only\n" * count),
        ("plain-delayed", "password:\n  river stone\n  quiet meadow\nmode: read-only\n" * count),
        ("block-looking", 'password: "river\n  api_key: |\n    stone"\nmode: read-only\n' * count),
        ("malformed", 'password: "unterminated\n  still unterminated\napi_key: short\n' * count),
        ("one-line", "password='sun''rise' " * count),
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
                "input_sha256": hashlib.sha256(source.encode()).hexdigest(),
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
print(f"{len(rows)} cases; maximum median {max(r['median_seconds'] for r in rows):.3f}s")
