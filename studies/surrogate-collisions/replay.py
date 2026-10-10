"""Controlled raw-text/CLI reproductions. All identities are fictitious.

Run with an installed Python, or --source CHECKOUT to load that checkout.
This is a reversibility and source-collision check, not a PII detection benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--label", default="checkout")
args = parser.parse_args()
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

import veil  # noqa: E402
from veil import (  # noqa: E402
    Masker,
    PlaceholderSurrogates,
    RealisticSurrogates,
    Restorer,
    VaultError,
)
from veil.backends.known_entities import KnownEntitiesBackend  # noqa: E402

results = []


def run_case(name, texts, *, realistic=False, persons=(), seed=None, reject=False, template=None):
    masker = Masker(
        surrogate_generator=(
            PlaceholderSurrogates(template=template)
            if template
            else RealisticSurrogates()
            if realistic
            else PlaceholderSurrogates()
        ),
        name_backends=[KnownEntitiesBackend(persons=list(persons))],
    )
    if seed:
        masker.mask(seed)
    before = masker.vault.to_dict()
    masked, restored, streamed, error = [], [], [], None
    try:
        if len(texts) > 1 and hasattr(masker, "mask_many"):
            masked = masker.mask_many(texts)
        else:
            # The baseline has only per-string masking. Rechecking restoration
            # after all inputs makes the cross-field ambiguity observable.
            masked = [masker.mask(text) for text in texts]
        restored = [masker.restore(text) for text in masked]
        for text in masked:
            restorer = Restorer(masker.vault)
            streamed.append("".join(restorer.feed(c) for c in text) + restorer.flush())
    except (VaultError, RuntimeError) as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    after = masker.vault.to_dict()
    leaked = [s for s in masker.vault.originals() if any(s in text for text in masked)]
    checks = {
        "expectedRejection": (error is not None) == reject,
        "reversible": error is not None if reject else restored == texts and streamed == texts,
        "noOriginalUsedAsReplacement": not leaked,
        "failedBatchPreservesVault": error is None or before == after,
        "errorOmitsOriginals": error is None
        or all(s not in error["message"] for s in masker.vault.originals()),
    }
    results.append(
        {
            "case": name,
            "source": texts,
            "priorSource": seed,
            "masked": masked,
            "restored": restored,
            "streamed": streamed,
            "expectedRejection": reject,
            "error": error,
            "beforeVault": before,
            "afterVault": after,
            "originalsInOutput": leaked,
            "checks": checks,
            "agrees": all(checks.values()),
        }
    )


run_case("plain-control", ["The weather is mild."])
run_case("email-control", ["Contact alice@example.org and bob@example.net."])
for literal in ["⟨EMAIL_1⟩", "⟨email_1⟩", "x⟨eMaIl_1⟩y"]:
    run_case("literal-" + literal, [f"Contact alice@example.org; example {literal}."])
run_case("two-literals", ["alice@example.org; examples ⟨EMAIL_1⟩ and ⟨EMAIL_2⟩."])
run_case("literal-in-earlier-field", ["Literal ⟨EMAIL_1⟩", "alice@example.org"])
run_case("literal-in-later-field", ["alice@example.org", "Literal ⟨EMAIL_1⟩"])
run_case("realistic-email-control", ["Contact alice@example.org."], realistic=True)
run_case("realistic-source-address", ["alice@example.org or user1@example.org"], realistic=True)
run_case(
    "realistic-address-across-fields", ["alice@example.org", "user1@example.org"], realistic=True
)
run_case(
    "realistic-source-name",
    ["Jordan Reyes met Blair Alder."],
    realistic=True,
    persons=["Jordan Reyes", "Blair Alder"],
)
run_case(
    "wrapped-name-literal",
    ["Jordan Reyes met BLAIR\n ALDER."],
    realistic=True,
    persons=["Jordan Reyes"],
)
run_case(
    "previous-original",
    ["Jordan Reyes"],
    seed="Casey Alder",
    realistic=True,
    persons=["Jordan Reyes", "Casey Alder"],
)
run_case("reused-vault-control", ["alice@example.org again"], seed="alice@example.org")
run_case("reused-literal-only", ["Example ⟨EMAIL_1⟩"], seed="alice@example.org", reject=True)
run_case(
    "reused-literal-and-new-mapping",
    ["new@example.org and ⟨email_1⟩"],
    seed="alice@example.org",
    reject=True,
)
run_case(
    "reused-batch-failure", ["new@example.org", "⟨EMAIL_1⟩"], seed="alice@example.org", reject=True
)
run_case(
    "unavailable-generator", ["alice@example.org and literal"], template="literal", reject=True
)
run_case("custom-template-control", ["alice@example.org"], template="[MASK_{type}_{n}]")
run_case(
    "custom-template-literal",
    ["alice@example.org and [MASK_EMAIL_1]"],
    template="[MASK_{type}_{n}]",
)


def cli_case(reuse):
    with tempfile.TemporaryDirectory(prefix="veil-collision-") as temporary:
        root = Path(temporary)
        vault_path, output = root / "vault.json", root / "out.txt"
        env = dict(os.environ)
        if args.source:
            env["PYTHONPATH"] = str(args.source.resolve() / "src")

        def invoke(text):
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "veil.cli",
                    "mask",
                    "--vault",
                    str(vault_path),
                    "-o",
                    str(output),
                ],
                input=text,
                text=True,
                capture_output=True,
                env=env,
                cwd=root,
                check=False,
            )

        if reuse:
            first = invoke("alice@example.org")
            assert first.returncode == 0
        before = vault_path.read_bytes() if vault_path.exists() else None
        output.write_bytes(b"previous output")
        text = (
            "new@example.org; literal ⟨EMAIL_1⟩"
            if reuse
            else "alice@example.org; literal ⟨EMAIL_1⟩"
        )
        text += "\n"
        run = invoke(text)
        after = vault_path.read_bytes()
        masked = output.read_text()
        vault = veil.Vault.from_json(after.decode())
        restored = veil.restore_exact(masked, vault)
        checks = {
            "exit": run.returncode == (2 if reuse else 0),
            "stdoutEmpty": not run.stdout,
            "output": masked == "previous output" if reuse else restored == text,
            "vault": before == after if reuse else len(vault) == 1,
            "noOriginalInError": "new@example.org" not in run.stderr
            and "alice@example.org" not in run.stderr,
        }
        results.append(
            {
                "case": "cli-reused-vault" if reuse else "cli-fresh-literal",
                "source": text,
                "exit": run.returncode,
                "stderr": run.stderr,
                "stdout": run.stdout,
                "output": masked,
                "restored": restored,
                "vaultSha256Before": hashlib.sha256(before).hexdigest() if before else None,
                "vaultSha256After": hashlib.sha256(after).hexdigest(),
                "checks": checks,
                "agrees": all(checks.values()),
            }
        )


cli_case(False)
cli_case(True)
modules = [
    "masker.py",
    "vault.py",
    "integrations/anthropic.py",
    "integrations/openai.py",
    "integrations/_common.py",
]
package = Path(veil.__file__).parent
print(
    json.dumps(
        {
            "label": args.label,
            "python": platform.python_version(),
            "scope": "Controlled fictitious inputs; exact and tolerant restoration, single-character streaming, and real CLI files. No model called.",
            "moduleSha256": {
                name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in modules
            },
            "cases": len(results),
            "disagreements": sum(not row["agrees"] for row in results),
            "results": results,
        },
        ensure_ascii=False,
        indent=2,
    )
)
