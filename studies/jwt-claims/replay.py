"""Capture complete JWT masking, CLI vaults and real SDK transport bytes.

Core/CLI replay needs no optional dependency. --oracle uses PyJWT and
cryptography to verify the retained native fixtures independently.
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
from veil.detectors import secrets as secrets_module

HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oracle", action="store_true")
    parser.add_argument("--sdk", action="store_true")
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    fixture = json.loads((HERE / "cases.json").read_text())
    rows = []
    with tempfile.TemporaryDirectory(prefix="veil-jwt-") as directory:
        for case in fixture["cases"]:
            token = case["token"]
            if args.oracle:
                import jwt

                assert (
                    jwt.decode(
                        token,
                        case["verificationKey"],
                        algorithms=[case["algorithm"]],
                        options={
                            "verify_exp": False,
                            "verify_signature": case["algorithm"] != "none",
                        },
                    )
                    == case["claims"]
                )
            source = f"Authorization: Bearer {token}\r\n"
            expected = "Authorization: Bearer ⟨SECRET_1⟩\r\n"
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
            cli = subprocess.run(
                [sys.executable, "-m", "veil.cli", "mask", "--vault", str(vault)],
                input=source.encode(),
                capture_output=True,
                check=True,
            )
            assert not cli.stderr and cli.stdout.decode() == masked
            restored = subprocess.run(
                [sys.executable, "-m", "veil.cli", "restore", "--exact", "--vault", str(vault)],
                input=cli.stdout,
                capture_output=True,
                check=True,
            )
            assert not restored.stderr and restored.stdout == source.encode()
            rows.append(
                {
                    "id": case["id"],
                    "algorithm": case["algorithm"],
                    "tokenCharacters": len(token),
                    "tokenSha256": hashlib.sha256(token.encode()).hexdigest(),
                    "masked": masked,
                    "correct": masked == expected,
                    "encodedClaimsStillVisible": token.split(".")[1] in masked,
                    "wholeTokenInVault": any(m.original == token for m in masker.vault.mappings()),
                    "exactCRLFRestore": True,
                    "streamChunkSizes": [1, 2, 7, 31],
                }
            )
    captures = []
    if args.sdk:
        capture = runpy.run_path(str(HERE.parent / "email-boundaries/replay.py"))["sdk_capture"]
        # Long, signed, unsigned, typ-optional and Unicode cases in one actual request.
        selected = [
            c
            for c in fixture["cases"]
            if c["id"]
            in {"hs256", "rs256", "es256", "unsecured", "no-typ", "unicode-claims", "long-claims"}
        ]
        source = "\n".join(f"Authorization: Bearer {c['token']}" for c in selected)
        expected = "\n".join(
            f"Authorization: Bearer ⟨SECRET_{i}⟩" for i in range(1, len(selected) + 1)
        )
        for api in ("chat", "responses", "anthropic"):
            for asynchronous in (False, True):
                for streaming in (False, True):
                    result = capture(source, api, asynchronous, streaming)
                    result["correct"] = result["outgoing"] == expected
                    captures.append(result)
    helper = Path(secrets_module.__file__).with_name("_jwt.py")
    report = {
        "python": sys.version.split()[0],
        "fixturesSha256": hashlib.sha256((HERE / "cases.json").read_bytes()).hexdigest(),
        "secretSourceSha256": hashlib.sha256(
            Path(secrets_module.__file__).read_bytes()
        ).hexdigest(),
        "jwtSourceSha256": hashlib.sha256(helper.read_bytes()).hexdigest()
        if helper.exists()
        else None,
        "cases": rows,
        "sdk": captures,
        "oracle": {
            "pyjwt": version("PyJWT"),
            "verifiedFixtures": len(rows),
            "timeClaimsChecked": False,
        }
        if args.oracle
        else None,
        "sdkVersions": {name: version(name) for name in ("openai", "anthropic")}
        if args.sdk
        else {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{sum(row['correct'] for row in rows)}/{len(rows)} whole JWTs; {sum(row['encodedClaimsStillVisible'] for row in rows)} visible claims; {sum(row['correct'] for row in captures)}/{len(captures)} SDK requests"
    )
    if args.require_fixed:
        assert all(
            row["correct"] and row["wholeTokenInVault"] and not row["encodedClaimsStillVisible"]
            for row in rows
        )
        assert all(row["correct"] for row in captures)


if __name__ == "__main__":
    main()
