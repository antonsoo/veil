"""Replay and review every changed resolved detection in the pinned corpus.

The fixed location sets record a manual reading of all 27 added matches.
Values stay out of the receipt; pinned URLs, offsets and hashes locate them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from veil import Masker

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent / "real-text"
VARIABLES = {
    ("code/psf-requests/a4598bf8444e0fec.py", 285),
    ("code/pallets-flask/d570ff9d63b49b50.rst", 236),
    ("code/pallets-flask/d570ff9d63b49b50.rst", 285),
    ("code/pallets-flask/0922d3b6872a3921.py", 53),
    ("code/pallets-flask/b84251b854d4b71a.py", 34),
    ("code/expressjs-express/7c376d97e1d98665.js", 68),
    ("code/axios-axios/586c04c24608b86a.js", 379),
}
LITERALS = {
    ("code/psf-requests/33c13e0b177bacd2.py", 411),
    ("code/pallets-flask/d570ff9d63b49b50.rst", 233),
    ("code/pallets-flask/d570ff9d63b49b50.rst", 267),
    ("code/pallets-flask/0922d3b6872a3921.py", 51),
    ("code/pallets-flask/b84251b854d4b71a.py", 13),
    ("code/expressjs-express/7c376d97e1d98665.js", 50),
    ("code/expressjs-express/c03f99ad1a5cf68a.js", 766),
    ("code/gin-gonic-gin/8e0465b1fc47504e.md", 623),
    ("code/fastify-fastify/ea8c7ac46bf4b207.md", 286),
    ("code/axios-axios/b335630551682c19.md", 450),
    ("code/axios-axios/b335630551682c19.md", 548),
    ("code/axios-axios/08038680ba612928.ts", 23),
    ("code/axios-axios/4759040bf102cb47.ts", 46),
    ("code/axios-axios/5bf12f55a72f043e.js", 21),
    ("code/axios-axios/5bf12f55a72f043e.js", 52),
    ("code/axios-axios/5bf12f55a72f043e.js", 68),
    ("code/axios-axios/44e027b25829495b.js", 731),
    ("code/axios-axios/44e027b25829495b.js", 1348),
    ("code/axios-axios/44e027b25829495b.js", 1427),
    ("code/axios-axios/796a99f96e36625e.js", 51),
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def entities(text: str) -> list[list]:
    return [
        [e.type.value, e.span.start, e.span.end, e.detector, e.confidence, e.value]
        for e in Masker().find_entities(text)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path, required=True)
    args = parser.parse_args()
    before = json.loads((HERE / "results/corpus-before.json").read_text())
    after = json.loads((HERE / "results/corpus-after.json").read_text())
    changed = []
    for old, new in zip(before["rows"], after["rows"], strict=True):
        assert old["file"] == new["file"] and old["sourceSha256"] == new["sourceSha256"]
        if old["detectionsSha256"] != new["detectionsSha256"]:
            changed.append((old, new))
    query = """
import json,sys
from pathlib import Path
from veil import Masker
out={}
for name in json.load(sys.stdin):
    text=(Path(sys.argv[1])/name).read_bytes().decode('utf-8',errors='replace')
    out[name]=[[e.type.value,e.span.start,e.span.end,e.detector,e.confidence,e.value] for e in Masker().find_entities(text)]
print(json.dumps(out))
"""
    baseline = json.loads(
        subprocess.run(
            [sys.executable, "-c", query, str(CORPUS / "cache")],
            env={**os.environ, "PYTHONPATH": str(args.baseline_source.resolve() / "src")},
            input=json.dumps([row["file"] for _, row in changed]),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    entries = {}
    for name in ("manifest-technical.json", "manifest-technical-heldout.json"):
        entries.update({r["name"]: r for r in json.loads((CORPUS / name).read_text())["files"]})
    rows = []
    seen = set()
    for old, new in changed:
        name = new["file"]
        raw = (CORPUS / "cache" / name).read_bytes()
        assert digest(raw) == old["sourceSha256"] == entries[name]["sha256"]
        text = raw.decode("utf-8", errors="replace")
        previous, current = baseline[name], entities(text)
        for receipt, found in ((old, previous), (new, current)):
            assert (
                digest(json.dumps(found, ensure_ascii=False, separators=(",", ":")).encode())
                == receipt["detectionsSha256"]
            )
        assert not [e for e in previous if e not in current], name
        for e in current:
            if e in previous:
                continue
            assert e[3] == "secret:credential_field"
            line = text.count("\n", 0, e[1]) + 1
            key = (name, line)
            assert key in VARIABLES | LITERALS and key not in seen, key
            seen.add(key)
            rows.append(
                {
                    "file": name,
                    "url": entries[name]["url"],
                    "sourceSha256": digest(raw),
                    "line": line,
                    "span": e[1:3],
                    "valueSha256": digest(e[5].encode()),
                    "classification": "source-variable-reference"
                    if key in VARIABLES
                    else "dummy-credential-literal",
                    "interpretation": "Collateral false positive; raw assignment syntax does not prove a literal."
                    if key in VARIABLES
                    else "Explicit test/documentation credential example; not a live secret.",
                }
            )
    assert seen == VARIABLES | LITERALS
    report = {
        "scope": __doc__,
        "files": after["files"],
        "bytes": after["bytes"],
        "words": after["words"],
        "changedFiles": len(changed),
        "unchangedFiles": after["files"] - len(changed),
        "added": len(rows),
        "removedOrChangedExisting": 0,
        "classification": dict(Counter(r["classification"] for r in rows)),
        "manifests": {
            name: digest((CORPUS / name).read_bytes())
            for name in ("manifest-technical.json", "manifest-technical-heldout.json")
        },
        "rows": rows,
    }
    (HERE / "results/corpus-review.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{len(rows)} reviewed additions in {len(changed)} files; {report['classification']}; no previous detection changed"
    )


if __name__ == "__main__":
    main()
