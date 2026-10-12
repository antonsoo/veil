"""Compare complete resolved detections on retained public technical text.

PYTHONPATH=<source>/src python studies/secret-formats/corpus.py <cache-root> <out.json>
No found values are printed or retained in this receipt.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from veil import Masker

study = Path(__file__).resolve().parents[1] / "real-text"
cache, output = map(Path, sys.argv[1:])
rows = []
for manifest in ["manifest-technical.json", "manifest-technical-heldout.json"]:
    for item in json.loads((study / manifest).read_text())["files"]:
        data = (cache / item["name"]).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if "sha256" in item:
            assert digest == item["sha256"], item["name"]
        text = data.decode("utf-8", errors="replace")
        found = Masker().find_entities(text)
        evidence = [
            [e.type.value, e.span.start, e.span.end, e.detector, e.confidence, e.value]
            for e in found
        ]
        rows.append(
            {
                "manifest": manifest,
                "file": item["name"],
                "sourceSha256": digest,
                "bytes": len(data),
                "words": len(text.split()),
                "detections": len(found),
                "detectionsSha256": hashlib.sha256(
                    json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode()
                ).hexdigest(),
            }
        )
report = {
    "python": sys.version.split()[0],
    "files": len(rows),
    "words": sum(r["words"] for r in rows),
    "bytes": sum(r["bytes"] for r in rows),
    "detections": sum(r["detections"] for r in rows),
    "rows": rows,
}
output.write_text(json.dumps(report, indent=2) + "\n")
print(f"{len(rows)} files, {report['words']} words, {report['detections']} resolved detections")
