"""Native key-recovery oracle and real masking workflows; no key bytes in receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import runpy
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

import veil
from veil import Masker, Restorer

HERE = Path(__file__).resolve().parent


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def recover(source: str, fingerprint: str) -> dict:
    """Import only retained base64 lines, sign, then independently verify.

    Rewrapping makes missing/changed armor comments and a missing END line
    irrelevant. OpenPGP packets remain the credential. GnuPG decides whether
    the retained bytes actually contain the expected usable private key.
    """
    lines = [
        line
        for line in source.splitlines()
        if re.fullmatch(r"[A-Za-z0-9+/]{1,76}={0,2}|=[A-Za-z0-9+/]{4}", line)
    ]
    candidate = (
        "-----BEGIN PGP PRIVATE KEY BLOCK-----\n\n"
        + "\n".join(lines)
        + "\n-----END PGP PRIVATE KEY BLOCK-----\n"
    )
    with tempfile.TemporaryDirectory(prefix="veil-gpg-recover-") as directory:
        home = Path(directory)
        command = [
            "gpg",
            "--no-options",
            "--homedir",
            str(home),
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
        ]
        try:
            imported = subprocess.run(
                [*command, "--import"], input=candidate.encode(), capture_output=True
            )
            listing = subprocess.run(
                [*command, "--with-colons", "--list-secret-keys"], capture_output=True, check=True
            ).stdout.decode()
            fingerprints = [
                line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")
            ]
            sign_code = verify_code = None
            verified = False
            if fingerprint in fingerprints:
                message = home / "challenge.txt"
                signature = home / "challenge.sig"
                message.write_text("Synthetic Veil key-recovery challenge.\n")
                signed = subprocess.run(
                    [
                        *command,
                        "--local-user",
                        fingerprint,
                        "--detach-sign",
                        "--output",
                        str(signature),
                        str(message),
                    ],
                    capture_output=True,
                )
                sign_code = signed.returncode
                if sign_code == 0:
                    checked = subprocess.run(
                        [*command, "--status-fd", "1", "--verify", str(signature), str(message)],
                        capture_output=True,
                    )
                    verify_code = checked.returncode
                    verified = (
                        verify_code == 0
                        and f"[GNUPG:] VALIDSIG {fingerprint} ".encode() in checked.stdout
                    )
            return {
                "retainedBase64Lines": len(lines),
                "importExit": imported.returncode,
                "expectedPrivateKeyImported": fingerprint in fingerprints,
                "signExit": sign_code,
                "verifyExit": verify_code,
                "usablePrivateKeyRecovered": verified,
            }
        finally:
            subprocess.run(
                ["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"],
                capture_output=True,
                check=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--sdk", action="store_true")
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((args.fixtures / "manifest.json").read_text())
    rows = []
    texts = {}
    with tempfile.TemporaryDirectory(prefix="veil-private-vault-") as directory:
        for case in manifest["cases"]:
            source = (args.fixtures / case["file"]).read_text()
            assert digest(source.encode()) == case["sourceSha256"]
            texts[case["id"]] = source
            expected = "⟨SECRET_1⟩" + source[case["privateEnd"] :]
            masker = Masker()
            masked = masker.mask(source)
            assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
            for size in (1, 2, 7, 31):
                restorer = Restorer(masker.vault)
                restored = (
                    "".join(
                        restorer.feed(masked[i : i + size]) for i in range(0, len(masked), size)
                    )
                    + restorer.flush()
                )
                assert restored == source
            vault = Path(directory) / f"{case['id']}.json"
            cli = subprocess.run(
                [sys.executable, "-m", "veil.cli", "mask", "--vault", str(vault)],
                input=source.encode(),
                capture_output=True,
                check=True,
            )
            assert not cli.stderr and cli.stdout.decode() == masked
            restored_cli = subprocess.run(
                [sys.executable, "-m", "veil.cli", "restore", "--exact", "--vault", str(vault)],
                input=cli.stdout,
                capture_output=True,
                check=True,
            )
            assert not restored_cli.stderr and restored_cli.stdout.decode() == source
            row = {
                **case,
                "maskedSha256": digest(masked.encode()),
                "maskedBytes": len(masked.encode()),
                "wholeBlockMasked": masked == expected,
                "entities": [
                    {
                        "type": e.type.value,
                        "detector": e.detector,
                        "span": [e.span.start, e.span.end],
                        "confidence": e.confidence,
                    }
                    for e in masker.find_entities(source)
                ],
                "exactCLIAndStreamRestoration": True,
            }
            if args.native:
                row["sourceRecovery"] = recover(source, case["fingerprint"])
                row["maskedRecovery"] = recover(masked, case["fingerprint"])
                if case["shape"] != "partial-body":
                    assert row["sourceRecovery"]["usablePrivateKeyRecovered"]
            rows.append(row)
    captures = []
    if args.sdk:
        capture = runpy.run_path(str(HERE.parent / "email-boundaries/replay.py"))["sdk_capture"]
        capture_tool = runpy.run_path(str(HERE.parent / "http-authorization/sdk_tools.py"))[
            "sdk_tool_capture"
        ]
        source = texts["email-complete"]
        end = next(c["privateEnd"] for c in manifest["cases"] if c["id"] == "email-complete")
        expected = "⟨SECRET_1⟩" + source[end:]
        raw_tool = json.dumps({"signing_material": source, "ordinary": "Keep"}, ensure_ascii=False)
        expected_tool = json.dumps(
            {"signing_material": expected, "ordinary": "Keep"}, ensure_ascii=False
        )
        for api in ("chat", "responses", "anthropic"):
            for asynchronous in (False, True):
                for streaming in (False, True):
                    row = capture(source, api, asynchronous, streaming)
                    # Request bodies and replies can contain a generated private
                    # key on baseline. Retain hashes and verified outcomes only.
                    captures.append(
                        {
                            "kind": "text",
                            "api": api,
                            "async": asynchronous,
                            "stream": streaming,
                            "wholeBlockMasked": row["outgoing"] == expected,
                            "outgoingSha256": digest(row["outgoing"].encode()),
                            "requestSha256": digest(
                                json.dumps(
                                    row["request"], ensure_ascii=False, sort_keys=True
                                ).encode()
                            ),
                            "exactRestoration": True,
                        }
                    )
                    row = capture_tool(
                        api,
                        asynchronous,
                        streaming,
                        source=raw_tool,
                        expected=expected_tool,
                        tool_reply=True,
                    )
                    captures.append(
                        {
                            "kind": "tool",
                            "api": api,
                            "async": asynchronous,
                            "stream": streaming,
                            "wholeBlockMasked": row["correct"],
                            "outgoingSha256": digest(row["outgoingArguments"].encode()),
                            "requestSha256": digest(
                                json.dumps(
                                    row["request"], ensure_ascii=False, sort_keys=True
                                ).encode()
                            ),
                            "exactRestoration": True,
                            "unrelatedSyntaxPreserved": row["unrelatedSyntaxPreserved"],
                        }
                    )
    root = Path(veil.__file__).parent
    report = {
        "scope": __doc__,
        "python": sys.version.split()[0],
        "versions": {name: version(name) for name in (("openai", "anthropic") if args.sdk else ())},
        "generator": {k: v for k, v in manifest.items() if k != "cases"},
        "runtimeFiles": {
            str(p.relative_to(root)): digest(p.read_bytes())
            for p in sorted(root.rglob("*"))
            if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")
        },
        "cases": rows,
        "sdk": captures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{sum(r['wholeBlockMasked'] for r in rows)}/{len(rows)} complete masks; {sum(r['wholeBlockMasked'] for r in captures)}/{len(captures)} SDK requests"
    )
    if args.native:
        print(
            f"Usable signing keys recovered from masked text: {sum(r['maskedRecovery']['usablePrivateKeyRecovered'] for r in rows)}/{len(rows)}"
        )
    if args.require_fixed:
        assert all(r["wholeBlockMasked"] for r in rows + captures)
        if args.native:
            assert not any(r["maskedRecovery"]["usablePrivateKeyRecovered"] for r in rows)


if __name__ == "__main__":
    main()
