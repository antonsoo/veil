"""Constructed scaling control derived from a retained native HAR.

Repeats native entries, optionally adding one literal placeholder example.
Times masking only, checks complete restoration and records output hashes.
This is not a naturally captured large session or a general speed guarantee.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--entries", type=int, nargs="+", default=[100, 500, 2000])
    parser.add_argument("--literal", choices=["both", "yes", "no"], default="both")
    args = parser.parse_args()
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import veil
    from veil import Masker

    native = json.loads((HERE / "fixtures/chromium.har").read_text())
    rows = []
    for entries in args.entries:
        for literal in [False, True] if args.literal == "both" else [args.literal == "yes"]:
            doc = {"log": {**native["log"], "entries": native["log"]["entries"] * (entries // 2)}}
            if literal:
                doc["log"]["_maskingExample"] = "literal ⟨SECRET_1⟩ stays literal"
            source = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
            samples, cpu_samples, hashes = [], [], set()
            for _ in range(args.repeat):
                masker = Masker()
                start = time.perf_counter()
                cpu_start = time.process_time()
                masked = masker.mask(source)
                samples.append(time.perf_counter() - start)
                cpu_samples.append(time.process_time() - cpu_start)
                assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
                assert len(masker.vault) == 5
                hashes.add(hashlib.sha256((masked + masker.vault.to_json()).encode()).hexdigest())
            assert len(hashes) == 1
            rows.append(
                {
                    "entries": entries,
                    "bytes": len(source.encode()),
                    "literalPlaceholder": literal,
                    "sourceSha256": hashlib.sha256(source.encode()).hexdigest(),
                    "seconds": samples,
                    "cpuSeconds": cpu_samples,
                    "medianSeconds": statistics.median(samples),
                    "outputAndVaultSha256": hashes.pop(),
                    "mappings": 5,
                    "exactAndTolerantRoundTrip": True,
                }
            )
            print(
                f"{entries} entries, literal={literal}: median {statistics.median(samples):.3f}s",
                flush=True,
            )
    package = Path(veil.__file__).resolve().parent
    result = {
        "scope": __doc__,
        "python": platform.python_version(),
        "repetitions": args.repeat,
        "maskerSha256": hashlib.sha256((package / "masker.py").read_bytes()).hexdigest(),
        "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rows": rows,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
