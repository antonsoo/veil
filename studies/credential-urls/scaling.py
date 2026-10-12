"""Time the URL detector alone on increasingly long ordinary parameter lists.

PYTHONPATH=<checkout>/src python scaling.py <receipt.json>
These synthetic timings check growth, not end-to-end throughput or recall.
"""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter

from veil.detectors import url

detector = url.UrlCredentialDetector()
rows = []
for field in ("topic=privacy&", "t%6Fpic=privacy&"):
    for size in (8192, 16384, 32768, 65536):
        text = "https://example.invalid/?" + field * size
        samples = []
        for _ in range(5):
            start = perf_counter()
            assert detector.find(text) == []
            samples.append((perf_counter() - start) * 1000)
        rows.append(
            {
                "field": field,
                "fields": size,
                "characters": len(text),
                "medianMs": statistics.median(samples),
                "samplesMs": samples,
            }
        )
report = {
    "python": platform.python_version(),
    "platform": platform.platform(),
    "detectorSha256": hashlib.sha256(Path(url.__file__).read_bytes()).hexdigest(),
    "rows": rows,
}
Path(sys.argv[1]).write_text(json.dumps(report, indent=2) + "\n")
for row in rows:
    print(f"{row['field']:16} {row['characters']:8} chars {row['medianMs']:8.2f} ms")
