"""Replay synthetic IDNA mailbox boundaries through core, CLI and real SDKs.

Use the desired environment's Python; PYTHONPATH may select baseline source.
SDK captures reuse the existing email-boundary study's local echo transport.
No credentials or external model calls are needed.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import runpy
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

from veil import Masker, Restorer
from veil.detectors import email as email_module
from veil.detectors.email import EmailDetector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOTS = ".\u3002\uff0e\uff61"


def cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(name: str, address: str, mask: bool = True) -> None:
        rows.append({"id": name, "address": address, "mask": mask})

    for index, dot in enumerate(DOTS[1:]):
        add(f"separator-{index}", f"alice@example{dot}org")
        add(f"suffix-{index}", f"alice@example.org{dot}private.example")
        add(f"international-{index}", f"利用者@例え{dot}テスト")
        for suffix in ("_private", "+private", "-", ".123", "." + "a" * 64):
            add(f"invalid-{index}-{len(rows)}", f"alice@example.org{dot}private{suffix}", False)
        add(f"empty-label-{index}", f"alice@example.org{dot}.private.example", False)
        add(f"invisible-{index}", f"alice@example.org{dot}pri\u200bvate.example", False)
        add(
            f"long-domain-{index}",
            f"alice@{'a' * 63}{dot}{'b' * 63}{dot}{'c' * 63}{dot}{'d' * 63}",
            False,
        )
    for index, separators in enumerate(itertools.product(DOTS, repeat=3)):
        a, b, c = separators
        add(f"mixed-{index}", f"a@one{a}two{b}three{c}example")
    for index, local in enumerate(("first!last", "o'reilly", '"private name"', "利用者")):
        add(f"local-{index}", f"{local}@例え\u3002example")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-fixed", action="store_true")
    parser.add_argument("--sdk", action="store_true")
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory(prefix="veil-idna-") as directory:
        for case in cases():
            source = f"Contact <{case['address']}> today.\r\n"
            expected = "Contact <⟨EMAIL_1⟩> today.\r\n" if case["mask"] else source
            if case["mask"]:
                # Independent IDNA codec confirms that this is a whole domain,
                # including suffixes beyond an ASCII-looking valid prefix.
                domain = case["address"].rsplit("@", 1)[1]
                encoded = domain.encode("idna").decode("ascii")
                assert encoded.count(".") == sum(domain.count(dot) for dot in DOTS)
            else:
                encoded = None
            masker = Masker()
            masked = masker.mask(source)
            assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
            for size in (1, 2, 7, 31):
                restorer = Restorer(masker.vault)
                reply = "".join(
                    restorer.feed(masked[i : i + size]) for i in range(0, len(masked), size)
                )
                assert reply + restorer.flush() == source
            vault = Path(directory) / f"{case['id']}.json"
            result = subprocess.run(
                [sys.executable, "-m", "veil.cli", "mask", "--vault", str(vault)],
                input=source.encode(),
                capture_output=True,
                check=True,
            )
            assert result.stderr == b"" and result.stdout.decode() == masked
            restored = subprocess.run(
                [sys.executable, "-m", "veil.cli", "restore", "--exact", "--vault", str(vault)],
                input=result.stdout,
                capture_output=True,
                check=True,
            )
            assert restored.stderr == b"" and restored.stdout == source.encode()
            found = [entity.value for entity in EmailDetector().find(source)]
            row = {
                **case,
                "idnaDomain": encoded,
                "masked": masked,
                "expected": expected,
                "entities": found,
                "correct": masked == expected,
                "cliMatchesCore": True,
                "exactCRLFRestore": True,
                "streamChunkSizes": [1, 2, 7, 31],
            }
            rows.append(row)

    sdk_rows = []
    if args.sdk:
        capture = runpy.run_path(str(HERE.parent / "email-boundaries/replay.py"))["sdk_capture"]
        selected = [
            case
            for case in cases()
            if case["id"].startswith(("separator-", "suffix-", "international-"))
        ]
        source = "\n".join(f"Contact <{case['address']}>." for case in selected)
        expected = "\n".join(f"Contact <⟨EMAIL_{i}⟩>." for i in range(1, len(selected) + 1))
        for api, asynchronous, streaming in itertools.product(
            ("chat", "responses", "anthropic"),
            (False, True),
            (False, True),
        ):
            result = capture(source, api, asynchronous, streaming)
            result["correct"] = result["outgoing"] == expected
            sdk_rows.append(result)
    report = {
        "python": sys.version.split()[0],
        "emailSourceSha256": hashlib.sha256(Path(email_module.__file__).read_bytes()).hexdigest(),
        "syntheticCases": len(rows),
        "correctCases": sum(row["correct"] for row in rows),
        "sdkRequests": len(sdk_rows),
        "correctSDKRequests": sum(row["correct"] for row in sdk_rows),
        "sdkVersions": {name: version(name) for name in ("openai", "anthropic")}
        if args.sdk
        else {},
        "cases": rows,
        "sdk": sdk_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{report['correctCases']}/{len(rows)} boundaries; {report['correctSDKRequests']}/{len(sdk_rows)} SDK requests; exact restoration passed"
    )
    if args.require_fixed:
        assert all(row["correct"] for row in rows + sdk_rows)


if __name__ == "__main__":
    main()
