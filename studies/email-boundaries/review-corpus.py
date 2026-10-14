"""Compare retained receipts and classify changed technical-text detections.

Run after corpus.py has generated before/after receipts and ignored details.
No contact values or surrounding text are written to the public receipt.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
before = json.loads((HERE / "results/corpus-before.json").read_text())
after = json.loads((HERE / "results/corpus-after.json").read_text())
details = json.loads((HERE / "cache/corpus-after.json").read_text())
rows = []
for b, a in zip(before["manifests"], after["manifests"], strict=True):
    assert b["sha256"] == a["sha256"] and b["filesDigest"] == a["filesDigest"]
    if "detections" not in b:
        rows.append(
            {
                "manifest": b["manifest"],
                "before": b["mailboxCoverage"],
                "after": a["mailboxCoverage"],
            }
        )
        continue

    def key(d: dict) -> tuple:
        return d["file"], tuple(d["span"]), d["sha256"]

    old = {key(d) for d in b["detections"]}
    added = [d for d in a["detections"] if key(d) not in old]
    new = {key(d) for d in a["detections"]}
    removed = [d for d in b["detections"] if key(d) not in new]
    counts: Counter[str] = Counter()
    classified = []
    for d in added:
        extended = any(
            o["file"] == d["file"] and d["span"][0] <= o["span"][0] and o["span"][1] <= d["span"][1]
            for o in removed
        )
        detail = next(
            x
            for x in details
            if x.get("manifest") == b["manifest"]
            and x.get("file") == d["file"]
            and x.get("span") == d["span"]
        )
        if extended:
            classification = "existing_mailbox_span_extended"
        elif "${GITHUB_ACTOR}" in detail["value"] or "{ENCODED_PASSWORD}" in detail["value"]:
            classification = "source_template_not_a_contact"
        else:
            # These contexts were also inspected by hand. Values are omitted
            # here; file, span, hash and the original manifests allow review.
            assert "'" in detail["context"], detail
            classification = "quoted_mailbox_occurrence_recovered"
        counts[classification] += 1
        classified.append({**d, "classification": classification})
    assert all(
        any(
            d["file"] == o["file"] and d["span"][0] <= o["span"][0] and o["span"][1] <= d["span"][1]
            for d in added
        )
        for o in removed
    )
    rows.append(
        {
            "manifest": b["manifest"],
            "words": a["words"],
            "before": b["count"],
            "after": a["count"],
            "removedSpansAllCoveredByLargerSpans": True,
            "changes": dict(counts),
            "changedDetections": classified,
        }
    )
(HERE / "results/corpus-review.json").write_text(json.dumps({"rows": rows}, indent=2) + "\n")
for row in rows:
    print(row["manifest"], row.get("changes", {"before": row["before"], "after": row["after"]}))
