"""Retain raw output, exact restoration and actual SDK request bodies.

No model service or external grader is called. --sdk uses installed SDKs
with the existing mock HTTP echo transport; omit it for a base-only wheel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

from veil import Masker, Restorer
from veil.detectors import _credential_fields

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sdk", action="store_true")
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory(prefix="yaml-credential-vault-") as directory:
        for case in json.loads((HERE / "fixtures/native.json").read_text())["cases"]:
            source = case["source"]
            masker = Masker()
            masked = masker.mask(source)
            assert masker.restore(masked, tolerant=False) == source
            for size in (1, 2, 7, 31):
                restorer = Restorer(masker.vault)
                restored = "".join(
                    restorer.feed(masked[i : i + size]) for i in range(0, len(masked), size)
                )
                assert restored + restorer.flush() == source
            vault = Path(directory) / f"{case['id']}.json"
            command = [sys.executable, "-m", "veil.cli"]
            output = subprocess.run(
                [*command, "mask", "--vault", str(vault)],
                input=source.encode(),
                capture_output=True,
                check=True,
            )
            assert not output.stderr and output.stdout == masked.encode()
            restored = subprocess.run(
                [*command, "restore", "--exact", "--vault", str(vault)],
                input=output.stdout,
                capture_output=True,
                check=True,
            )
            assert not restored.stderr and restored.stdout == source.encode()
            rows.append(
                {
                    "id": case["id"],
                    "input_sha256": case["source_sha256"],
                    "masked": masked,
                    "protected": all(value not in masked for value in case["sensitive_fragments"]),
                    "exact_cli_and_stream_restore": True,
                    "vault": [
                        {"original": m.original, "surrogate": m.surrogate}
                        for m in masker.vault.mappings()
                    ],
                }
            )
    sdk = []
    if args.sdk:
        capture = runpy.run_path(str(HERE.parent / "email-boundaries/replay.py"))["sdk_capture"]
        source = (
            "Local integration failure. Keep mode and status for diagnosis.\n"
            "connection:\n  password: |-\n    river\n    stone\n  mode: read-only\n"
            "client_secret: >-\n  quiet\n  meadow\nstatus: failed\n"
        )
        for api in ("chat", "responses", "anthropic"):
            for asynchronous in (False, True):
                for streaming in (False, True):
                    row = capture(source, api, asynchronous, streaming)
                    row["protected"] = all(
                        word not in row["outgoing"]
                        for word in ("river", "stone", "quiet", "meadow")
                    )
                    sdk.append(row)
    result = {
        "runtime_sha256": hashlib.sha256(
            Path(_credential_fields.__file__).read_bytes()
        ).hexdigest(),
        "synthetic": True,
        "native_cases": rows,
        "sdk_requests": sdk,
        "versions": {
            name: version(name)
            for name in (["veil-pii", "openai", "anthropic"] if args.sdk else ["veil-pii"])
        },
        "protected_native": sum(row["protected"] for row in rows),
        "protected_sdk": sum(row["protected"] for row in sdk),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: result[key] for key in ("protected_native", "protected_sdk")}))
    if args.require_fixed:
        assert all(row["protected"] for row in [*rows, *sdk])


if __name__ == "__main__":
    main()
