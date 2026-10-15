"""Bounded header inspection and compact-token scanning, not JWT verification."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import statistics
import time
from pathlib import Path

from veil.detectors import secrets as secrets_module
from veil.detectors.secrets import SecretDetector


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    detector = SecretDetector()
    rows = []
    header = b64(b'{"alg":"HS256","typ":"JWT"}')
    for size in (10_000, 100_000, 1_000_000):
        cases = {
            "opaque-claims": f"{header}.{b64(json.dumps({'notes': 'x' * size}).encode())}.c3ludGhldGlj",
            "oversized-header": f"{'A' * size}.e30.c3ludGhldGlj",
            "one-long-word": "a" * size,
            "many-dots": "a." * (size // 2),
            "four-parts": (f"{header}.e30.signature.additional ") * max(1, size // 80),
        }
        for name, text in cases.items():
            detector.find(text)
            samples = []
            for _ in range(3):
                start = time.perf_counter()
                found = detector.find(text)
                samples.append(time.perf_counter() - start)
            rows.append(
                {
                    "shape": name,
                    "inputBytes": len(text.encode()),
                    "inputSha256": hashlib.sha256(text.encode()).hexdigest(),
                    "medianSeconds": statistics.median(samples),
                    "seconds": samples,
                    "entities": len(found),
                    "wholeInputMasked": any(e.value == text for e in found),
                }
            )
    helper = Path(secrets_module.__file__).with_name("_jwt.py")
    report = {
        "python": platform.python_version(),
        "logicalCPUs": os.cpu_count(),
        "platform": platform.system(),
        "secretSourceSha256": hashlib.sha256(
            Path(secrets_module.__file__).read_bytes()
        ).hexdigest(),
        "jwtSourceSha256": hashlib.sha256(helper.read_bytes()).hexdigest()
        if helper.exists()
        else None,
        "warmups": 1,
        "repeats": 3,
        "scope": "SecretDetector.find only; synthetic structure, not verified signatures.",
        "rows": rows,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for row in rows:
        print(
            f"{row['shape']}: {row['inputBytes']} bytes, {row['medianSeconds']:.4f}s, {row['entities']} entities"
        )


if __name__ == "__main__":
    main()
