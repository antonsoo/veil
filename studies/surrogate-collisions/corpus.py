"""Replay masking and restoration on the cached, hash-checked technical corpus.

No source text or vault is retained. See ../real-text for sources and licences.
An output-ledger hash compares every masked text and mapping, not just counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--label", default="checkout")
args = parser.parse_args()
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

from veil import Masker, VaultError  # noqa: E402

corpus = Path(__file__).resolve().parents[1] / "real-text"
started = time.perf_counter()
ledgers, groups = [], []
for name in ["manifest-technical.json", "manifest-technical-heldout.json"]:
    entries = json.loads((corpus / name).read_text())["files"]
    counts = {
        "manifest": name,
        "files": 0,
        "bytes": 0,
        "mappings": 0,
        "refused": 0,
        "changedOnRestore": 0,
    }
    exceptions = []
    for entry in entries:
        data = (corpus / "cache" / entry["name"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["name"]
        assert len(data) == entry["bytes"], entry["name"]
        text = data.decode("utf-8")
        masker = Masker()
        try:
            masked = masker.mask(text)
            exact = masker.restore(masked, tolerant=False) == text
            tolerant = masker.restore(masked) == text
            counts["changedOnRestore"] += not (exact and tolerant)
            row = {
                "file": entry["name"],
                "sourceSha256": entry["sha256"],
                "maskedSha256": hashlib.sha256(masked.encode()).hexdigest(),
                "vaultSha256": hashlib.sha256(masker.vault.to_json().encode()).hexdigest(),
                "exactRoundTrip": exact,
                "tolerantRoundTrip": tolerant,
            }
            counts["mappings"] += len(masker.vault)
        except VaultError as exc:
            counts["refused"] += 1
            row = {"file": entry["name"], "sourceSha256": entry["sha256"], "error": str(exc)}
            exceptions.append(row)
        ledgers.append(row)
        counts["files"] += 1
        counts["bytes"] += len(data)
    groups.append({**counts, "exceptions": exceptions})
    print(f"Completed {name}: {counts['files']} files", file=sys.stderr)

print(
    json.dumps(
        {
            "label": args.label,
            "python": platform.python_version(),
            "scope": "Existing public technical corpus, default detectors/placeholders, fresh vault per file. Not a detection-accuracy measurement.",
            "groups": groups,
            "elapsedSeconds": round(time.perf_counter() - started, 3),
            "outputLedgerSha256": hashlib.sha256(
                json.dumps(ledgers, sort_keys=True).encode()
            ).hexdigest(),
        },
        indent=2,
    )
)
