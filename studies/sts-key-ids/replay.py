"""Replay synthetic AWS access key ID masking; no AWS or model calls.

The seeded sample uses the current key body's base32 alphabet, not real keys
or an empirical distribution of issued credentials. SDK transport capture is
shared with the existing mailbox study.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import runpy
import string
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

from veil import Masker, Restorer
from veil.detectors import secrets as secrets_module
from veil.detectors.secrets import SecretDetector

HERE = Path(__file__).resolve().parent
SEED = 20261015
EXAMPLES = [
    "ASIA4J2RI3GSPL7SLMJN",
    "ASIAYSY3Y52XLD7NZ34H",
    "ASIAZKCBPDZKGSLHIEPC",
    "ASIAAHW63PIK6ALWRAOT",
    "AKIA4J2RI3GSPL7SLMJN",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sdk", action="store_true")
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    detector = SecretDetector()
    generator = random.Random(SEED)
    bodies = [
        "".join(generator.choices(string.ascii_uppercase + "234567", k=16)) for _ in range(1000)
    ]
    assert len(set(bodies)) == len(bodies)
    counts = {}
    for prefix in ("AKIA", "ASIA"):
        rows = [
            [prefix + body, [(e.value, e.detector) for e in detector.find(prefix + body)]]
            for body in bodies
        ]
        counts[prefix] = {
            "generated": len(rows),
            "completelyRecognized": sum(
                any(value == key for value, _ in found) for key, found in rows
            ),
            "explicitlyRecognized": sum(
                any(value == key and source == "secret:aws_access_key" for value, source in found)
                for key, found in rows
            ),
            "rowsSha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
        }
    cases = []
    with tempfile.TemporaryDirectory(prefix="veil-sts-") as directory:
        for key in EXAMPLES:
            source = f'export AWS_ACCESS_KEY_ID="{key}"\r\n'
            expected = 'export AWS_ACCESS_KEY_ID="⟨SECRET_1⟩"\r\n'
            masker = Masker()
            masked = masker.mask(source)
            assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
            for size in (1, 2, 7, 31):
                restorer = Restorer(masker.vault)
                result = "".join(
                    restorer.feed(masked[i : i + size]) for i in range(0, len(masked), size)
                )
                assert result + restorer.flush() == source
            vault = Path(directory) / f"{key}.json"
            masked_cli = subprocess.run(
                [sys.executable, "-m", "veil.cli", "mask", "--vault", str(vault)],
                input=source.encode(),
                capture_output=True,
                check=True,
            )
            assert masked_cli.stderr == b"" and masked_cli.stdout.decode() == masked
            restored_cli = subprocess.run(
                [sys.executable, "-m", "veil.cli", "restore", "--exact", "--vault", str(vault)],
                input=masked_cli.stdout,
                capture_output=True,
                check=True,
            )
            assert restored_cli.stderr == b"" and restored_cli.stdout == source.encode()
            cases.append(
                {
                    "key": key,
                    "masked": masked,
                    "expected": expected,
                    "correct": masked == expected,
                    "cliMatchesCore": True,
                    "exactCRLFRestore": True,
                    "streamChunkSizes": [1, 2, 7, 31],
                }
            )
    captures = []
    if args.sdk:
        capture = runpy.run_path(str(HERE.parent / "email-boundaries/replay.py"))["sdk_capture"]
        source = "\n".join(f'AWS_ACCESS_KEY_ID="{key}"' for key in EXAMPLES)
        expected = "\n".join(
            f'AWS_ACCESS_KEY_ID="⟨SECRET_{i}⟩"' for i in range(1, len(EXAMPLES) + 1)
        )
        for api in ("chat", "responses", "anthropic"):
            for asynchronous in (False, True):
                for streaming in (False, True):
                    row = capture(source, api, asynchronous, streaming)
                    row["correct"] = row["outgoing"] == expected
                    captures.append(row)
    report = {
        "provenance": "Synthetic key-shaped identifiers, not issued credentials; no AWS or model calls.",
        "seed": SEED,
        "bodyAlphabet": string.ascii_uppercase + "234567",
        "python": sys.version.split()[0],
        "secretSourceSha256": hashlib.sha256(
            Path(secrets_module.__file__).read_bytes()
        ).hexdigest(),
        "counts": counts,
        "cases": cases,
        "sdk": captures,
        "sdkVersions": {name: version(name) for name in ("openai", "anthropic")}
        if args.sdk
        else {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "counts": counts,
                "correctSDKRequests": sum(row["correct"] for row in captures),
                "sdkRequests": len(captures),
            }
        )
    )
    if args.require_fixed:
        assert all(
            value["completelyRecognized"] == value["explicitlyRecognized"] == 1000
            for value in counts.values()
        )
        assert all(row["correct"] for row in cases + captures)


if __name__ == "__main__":
    main()
