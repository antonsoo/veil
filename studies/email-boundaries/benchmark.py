"""Bounded-candidate timing receipt; constructed inputs, not real accuracy data."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from veil.detectors.email import EmailDetector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for name, unit in [
        ("long-atom", "a" * 200_000 + "@example.org"),
        ("escaped-quotes", '\\"' * 100_000 + "@example.org"),
        ("many-at-signs", "a@a." * 50_000),
        ("mailbox-export", "first!last@example.org\n" * 10_000),
    ]:
        durations = []
        for _ in range(5):
            started = time.perf_counter()
            found = EmailDetector().find(unit)
            durations.append(time.perf_counter() - started)
        rows.append(
            {
                "case": name,
                "bytes": len(unit.encode()),
                "sha256": hashlib.sha256(unit.encode()).hexdigest(),
                "detections": len(found),
                "medianSeconds": statistics.median(durations),
                "seconds": durations,
            }
        )
    result = {
        "machine": platform.platform(),
        "python": platform.python_version(),
        "host": "14 vCPU WSL2 Linux, 48 GB RAM",
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
