"""Generate unused synthetic GnuPG signing keys into an explicit local directory.

Never points GnuPG at the user's keyring and never contacts a keyserver.
The private inputs stay in that directory, outside committed study evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

COMMENTS = {
    "ordinary": "synthetic recovery study",
    "email": "synthetic-owner@example.org",
    "ipv4": "10.23.45.67",
    "card": "4111111111111111",
    "iban": "GB82 WEST 1234 5698 7654 32",
    "credential-field": "password=short-value",
}


def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (destination / "manifest.json").exists():
        raise ValueError("A fixture manifest already exists; replay it or choose a new directory")
    with tempfile.TemporaryDirectory(prefix="gpg-producer-", dir=destination) as temporary:
        home = Path(temporary)
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
            subprocess.run(
                [
                    *command,
                    "--quick-generate-key",
                    "Synthetic Veil study <unused@example.invalid>",
                    "ed25519",
                    "sign",
                    "0",
                ],
                capture_output=True,
                check=True,
            )
            listing = subprocess.run(
                [*command, "--with-colons", "--list-secret-keys"], capture_output=True, check=True
            ).stdout.decode()
            fingerprint = next(
                line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")
            )
            rows = []
            for name, comment in COMMENTS.items():
                armor = subprocess.run(
                    [
                        *command,
                        "--armor",
                        "--comment",
                        comment,
                        "--export-secret-keys",
                        fingerprint,
                    ],
                    capture_output=True,
                    check=True,
                ).stdout.decode()
                payload = armor.split("\n\n", 1)[1].split("-----END", 1)[0].rstrip("\n")
                no_footer = armor[: armor.index("-----END")].rstrip("\n")
                partial = no_footer[: no_footer.index("\n\n") + 2] + "\n".join(
                    payload.splitlines()[:3]
                )
                for shape, value in (
                    ("complete", armor.rstrip("\n")),
                    ("no-footer", no_footer),
                    ("partial-body", partial),
                ):
                    source = value + "\n!Diagnostic context is outside the export.\n"
                    private_end = len(value) + (shape != "complete")
                    identifier = f"{name}-{shape}"
                    path = destination / f"{identifier}.txt"
                    path.write_text(source)
                    os.chmod(path, 0o600)
                    rows.append(
                        {
                            "id": identifier,
                            "file": path.name,
                            "comment": comment,
                            "shape": shape,
                            "sourceSha256": hashlib.sha256(source.encode()).hexdigest(),
                            "bytes": len(source.encode()),
                            "privateEnd": private_end,
                            "fingerprint": fingerprint,
                            "completePayloadSha256": hashlib.sha256(payload.encode()).hexdigest(),
                        }
                    )
            report = {
                "provenance": __doc__,
                "generator": "GnuPG --quick-generate-key ed25519 sign 0; --armor --comment --export-secret-keys",
                "gpgVersion": subprocess.run(
                    [*command, "--version"], capture_output=True, check=True
                )
                .stdout.decode()
                .splitlines()[:2],
                "cases": rows,
            }
            (destination / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
        finally:
            subprocess.run(
                ["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"],
                capture_output=True,
                check=True,
            )
    print(f"Generated {len(rows)} native/derived fixtures; private inputs remain local")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    generate(parser.parse_args().destination)
