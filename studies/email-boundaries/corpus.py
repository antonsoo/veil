"""Recheck the retained 2026-10-01 OSM and technical corpus, without publishing contacts.

Requires the ignored, previously collected studies/real-text/cache files.
The before and after receipts include hashes and counts; local --details are
for manual review and should stay in cache/ (they contain public contact data).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

from veil.detectors import email as email_module
from veil.detectors.email import EmailDetector

HERE = Path(__file__).resolve().parent
REAL = HERE.parent / "real-text"
spec = importlib.util.spec_from_file_location("real_text", REAL / "evaluate.py")
assert spec is not None and spec.loader is not None
real = importlib.util.module_from_spec(spec)
spec.loader.exec_module(real)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--details", type=Path, required=True)
    args = parser.parse_args()
    detector = EmailDetector()
    manifests: list[dict[str, Any]] = []
    details = []
    for name in ("manifest-osm.json", "manifest-osm-heldout.json"):
        raw = (REAL / name).read_bytes()
        manifest = json.loads(raw)
        counts: Counter[str] = Counter()
        files = []
        for city in manifest["cities"]:
            path = REAL / "cache" / "osm" / city["file"]
            contents = path.read_bytes()
            assert digest(contents) == city["sha256"], path
            files.append({"file": city["file"], "sha256": digest(contents)})
            for element in real.sample(json.loads(contents)["elements"]):
                line, gold = real.render(element)
                entities = detector.find(line)
                for item in gold:
                    if item["kind"] != "email" or "@" not in item["value"]:
                        continue
                    outcome, _ = real.coverage(line, item["start"], item["end"], entities, "EMAIL")
                    counts[outcome] += 1
                    if outcome != "found":
                        details.append(
                            {
                                "manifest": name,
                                "city": city["city"],
                                "outcome": outcome,
                                "value": item["value"],
                            }
                        )
        manifests.append(
            {
                "manifest": name,
                "sha256": digest(raw),
                "verifiedFiles": len(files),
                "filesDigest": digest(json.dumps(files, sort_keys=True).encode()),
                "mailboxCoverage": dict(sorted(counts.items())),
            }
        )
    for name in ("manifest-technical.json", "manifest-technical-heldout.json"):
        raw = (REAL / name).read_bytes()
        manifest = json.loads(raw)
        detections = []
        words = 0
        files = []
        for item in manifest["files"]:
            path = REAL / "cache" / item["name"]
            contents = path.read_bytes()
            assert digest(contents) == item["sha256"], path
            files.append({"file": item["name"], "sha256": digest(contents)})
            text = contents.decode("utf-8", errors="replace")
            words += real.words(text)
            for entity in detector.find(text):
                record = {
                    "file": item["name"],
                    "span": [entity.span.start, entity.span.end],
                    "sha256": digest(entity.value.encode()),
                }
                detections.append(record)
                details.append(
                    {
                        "manifest": name,
                        **record,
                        "value": entity.value,
                        "context": text[max(0, entity.span.start - 55) : entity.span.end + 55],
                    }
                )
        manifests.append(
            {
                "manifest": name,
                "sha256": digest(raw),
                "verifiedFiles": len(files),
                "filesDigest": digest(json.dumps(files, sort_keys=True).encode()),
                "words": words,
                "detections": detections,
                "count": len(detections),
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "emailSourceSha256": digest(Path(email_module.__file__).read_bytes()),
                "manifests": manifests,
            },
            indent=2,
        )
        + "\n"
    )
    args.details.parent.mkdir(parents=True, exist_ok=True)
    args.details.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n")
    for receipt in manifests:
        print(receipt["manifest"], receipt.get("mailboxCoverage", receipt.get("count")))


if __name__ == "__main__":
    main()
