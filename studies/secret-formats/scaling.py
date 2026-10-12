"""Measure the detector on large synthetic token bodies; no timing assertions."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from veil.detectors import secrets

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
rows = []
for shape, body in (("single-body", "a"), ("nested-prefixes", "sk-proj-")):
    for length in (10_000, 100_000, 1_000_000):
        token = "sk-proj-" + (body * ((length + len(body) - 1) // len(body)))[:length]
        source = f'Use "{token}" once.'
        detector = secrets.SecretDetector()
        elapsed = []
        for iteration in range(6):
            started = time.perf_counter()
            found = detector.find(source)
            duration = time.perf_counter() - started
            assert len(found) == 1 and found[0].value == token
            if iteration:
                elapsed.append(duration * 1000)
        rows.append(
            {
                "shape": shape,
                "bodyCharacters": length,
                "milliseconds": elapsed,
                "medianMs": statistics.median(elapsed),
            }
        )
report = {
    "python": platform.python_version(),
    "secretDetectorSha256": hashlib.sha256(Path(secrets.__file__).read_bytes()).hexdigest(),
    "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "scope": "SecretDetector.find only, one warm-up and five timed calls; controlled synthetic shapes, not a throughput guarantee",
    "rows": rows,
}
args.output.write_text(json.dumps(report, indent=2) + "\n")
for row in rows:
    print(f"{row['shape']} {row['bodyCharacters']}: {row['medianMs']:.3f} ms median")
