"""Probe scanner scaling on constructed malformed tokens, not a throughput claim."""

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from veil.detectors import ip

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path)
args = parser.parse_args()
rows = []
for shape, unit, prefix, suffix in [
    ("hex", "a", "", "z"),
    ("colons", ":", "2001:db8::", "z"),
    ("dotted-colons", "1.2:3", "2001:db8::", "z"),
    ("dotted-number", "1.", "", "z"),
    ("scope", "en0%2D", "fe80::1%", "%2G"),
]:
    for size in (10_000, 100_000, 1_000_000):
        text = prefix + (unit * ((size + len(unit) - 1) // len(unit)))[:size] + suffix
        ip.IpDetector().find(text)
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            assert ip.IpDetector().find(text) == []
            samples.append((time.perf_counter() - start) * 1000)
        rows.append(
            {
                "shape": shape,
                "characters": len(text),
                "medianMs": statistics.median(samples),
                "milliseconds": samples,
            }
        )
report = {
    "python": platform.python_version(),
    "machine": "14-vCPU WSL2 Linux; shared host, not isolated",
    "scope": "IpDetector.find only; one warmup, five samples; no timing assertion",
    "detectorSha256": hashlib.sha256(Path(ip.__file__).read_bytes()).hexdigest(),
    "rows": rows,
}
args.output.write_text(json.dumps(report, indent=2) + "\n")
print([(r["shape"], r["characters"], round(r["medianMs"], 2)) for r in rows])
