"""Check actual installed CLI stdin/stdout and saved vaults with synthetic tokens."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from cases import cases

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bin", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--baseline", action="store_true")
args = parser.parse_args()


def run(*command: str, text: str = "") -> str:
    result = subprocess.run(
        [str(args.bin.resolve()), *command], input=text, text=True, capture_output=True, check=True
    )
    assert result.stderr == "", result.stderr
    return result.stdout


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


rows = []
with tempfile.TemporaryDirectory(prefix="veil-synthetic-keys-") as directory:
    for c in cases():
        source = f'Use "{c["token"]}" once; leave this sentence.\n'
        vault_file = Path(directory) / f"{c['id']}.json"
        masked = run("mask", "--vault", str(vault_file), text=source)
        restored = run("restore", "--exact", "--vault", str(vault_file), text=masked)
        mappings = json.loads(vault_file.read_text())["mappings"]
        row = {
            "id": c["id"],
            "sourceSha256": digest(source),
            "maskedSha256": digest(masked),
            "fullyMasked": masked == 'Use "⟨SECRET_1⟩" once; leave this sentence.\n',
            "wholeTokenMapping": len(mappings) == 1 and mappings[0]["original"] == c["token"],
            "restoresExactly": restored == source,
        }
        assert row["restoresExactly"], c["id"]
        if not args.baseline:
            assert row["fullyMasked"] and row["wholeTokenMapping"], c["id"]
        rows.append(row)
report = {
    "versionOutput": run("--version").strip(),
    "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "casesSha256": hashlib.sha256(Path(__file__).with_name("cases.py").read_bytes()).hexdigest(),
    "cases": len(rows),
    "cliCalls": 2 * len(rows),
    "fullyMasked": sum(r["fullyMasked"] for r in rows),
    "restoresExactly": sum(r["restoresExactly"] for r in rows),
    "rows": rows,
}
args.output.write_text(json.dumps(report, indent=2) + "\n")
print(f"{report['fullyMasked']}/{len(rows)} complete masks; all saved vaults restore exactly")
