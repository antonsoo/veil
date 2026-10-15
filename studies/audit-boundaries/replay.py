"""Replay synthetic known-value audit boundaries through the public API and CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veil.audit import audit, find_leaked_originals, find_new_pii
from veil.detectors.base import Detector
from veil.detectors.url import UrlCredentialDetector
from veil.masker import Masker
from veil.types import Entity, EntityType, Span
from veil.vault import Vault


@dataclass
class LiteralDetector:
    """Synthetic caller-supplied detector for short, overlapping boundary probes."""

    value: str
    name: str = "controlled_literal"

    def find(self, text: str) -> list[Entity]:
        out = []
        at = text.find(self.value)
        while at >= 0:
            out.append(
                Entity(EntityType.PERSON, self.value, Span(at, at + len(self.value)), self.name)
            )
            at = text.find(self.value, at + 1)
        return out


def vault_for(*originals: str, surrogate: str | None = None) -> Vault:
    return Vault.from_dict(
        {
            "version": 1,
            "mappings": [
                {"type": "SECRET", "original": value, "surrogate": surrogate or f"⟨SECRET_{i}⟩"}
                for i, value in enumerate(originals, 1)
            ],
        }
    )


def summary(findings: Any) -> list[dict[str, Any]]:
    return [
        {
            "kind": f.kind,
            "type": f.entity.type.value,
            "value": f.entity.value,
            "start": f.entity.span.start,
            "end": f.entity.span.end,
        }
        for f in findings
    ]


def invoke(*arguments: str, source: str = "") -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "veil.cli", *arguments],
        input=source,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.stderr == "", result.stderr
    return result


def cli_capture(text: str, vault: Vault, roundtrip: str | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="veil-audit-boundaries-") as directory:
        root = Path(directory)
        vp = root / "vault.json"
        if roundtrip is None:
            vault.save(str(vp))
        else:
            masked = invoke("mask", "--vault", str(vp), source=roundtrip)
            assert masked.returncode == 0
            restored = invoke("restore", "--exact", "--vault", str(vp), source=masked.stdout)
            assert restored.returncode == 0 and restored.stdout == roundtrip + "\n"
            assert Vault.load(str(vp)).to_dict() == vault.to_dict()
        result = invoke("audit", "--json", "--vault", str(vp), source=text)
        payload = json.loads(result.stdout)
        assert result.returncode == (1 if payload else 0)
        return {
            "exitCode": result.returncode,
            "findings": payload,
            "cliMaskRestoreExact": roundtrip is not None,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    rows = []

    def capture(
        name: str,
        text: str,
        vault: Vault,
        expected_new: list[str],
        *,
        detectors: list[Detector] | None = None,
        cli: bool = False,
        roundtrip: str | None = None,
    ) -> None:
        new = summary(find_new_pii(text, vault, detectors))
        leaks = summary(find_leaked_originals(text, vault))
        combined = summary(audit(text, vault, detectors))
        assert sorted(leaks + new, key=lambda row: row["start"]) == combined
        expected = sorted(expected_new)
        matches = sorted(row["value"] for row in new) == expected
        row = {
            "case": name,
            "text": text,
            "vault": vault.to_dict(),
            "newPii": new,
            "leakedOriginals": leaks,
            "combined": combined,
            "expectedNewValues": expected,
            "expectedNewValuesMatch": matches,
        }
        if cli:
            row["cli"] = cli_capture(text, vault, roundtrip)
            cli_rows = [
                {k: v for k, v in value.items() if k != "detector"}
                for value in row["cli"]["findings"]
            ]
            assert cli_rows == combined
        rows.append(row)
        if args.require_fixed:
            assert matches, name
        print(
            f"{name:33} known leaks {len(leaks)}; new {len(new)}; expected new {len(expected)}; "
            f"{'PASS' if matches else 'MISMATCH'}",
            flush=True,
        )

    mail_url = "https://files.example.test/share?token=alice@example.com"
    ip_url = "https://203.0.113.42/archive?token=synthetic-private"
    for name, original in [("known-url-mailbox", mail_url), ("known-url-ip", ip_url)]:
        masker = Masker()
        masked = masker.mask(original)
        assert len(masker.vault) == 1
        assert masker.restore(masked, tolerant=False) == original
        capture(name, original, masker.vault, [], cli=True, roundtrip=original)
    masker = Masker()
    masker.mask(mail_url)
    capture(
        "new-mailbox-outside-known-url",
        mail_url + "\nNew: bob@example.com",
        masker.vault,
        ["bob@example.com"],
        cli=True,
        roundtrip=mail_url,
    )
    capture(
        "same-mailbox-outside-known-url",
        mail_url + "\nStandalone: alice@example.com",
        masker.vault,
        ["alice@example.com"],
    )
    capture(
        "changed-url-is-still-new",
        ip_url.replace("archive", "changed"),
        vault_for(ip_url),
        [ip_url.replace("archive", "changed")],
        detectors=[UrlCredentialDetector()],
    )
    fake_url = "https://surrogate.example.test/share?token=fake@example.com"
    capture(
        "known-surrogate-embedded-mailbox",
        fake_url,
        vault_for(mail_url, surrogate=fake_url),
        [],
        cli=True,
    )
    capture(
        "new-next-to-known-surrogate",
        fake_url + "\nbob@example.com",
        vault_for(mail_url, surrogate=fake_url),
        ["bob@example.com"],
        cli=True,
    )
    capture(
        "known-email-inside-new-url",
        mail_url,
        vault_for("alice@example.com"),
        [mail_url],
        detectors=[UrlCredentialDetector()],
    )
    capture(
        "overlapping-original-occurrences",
        "ababa",
        vault_for("aba"),
        [],
        detectors=[LiteralDetector("ba")],
    )
    capture(
        "adjacent-known-values-not-unioned",
        "secretAsecretB",
        vault_for("secretA", "secretB"),
        ["Asecret"],
        detectors=[LiteralDetector("Asecret")],
    )
    capture(
        "crosses-known-value-boundary",
        "secretAoutside",
        vault_for("secretA"),
        ["Aoutside"],
        detectors=[LiteralDetector("Aoutside")],
    )
    capture(
        "partial-unknown-overlap",
        "xxsecretA",
        vault_for("secretA"),
        ["xxsecret"],
        detectors=[LiteralDetector("xxsecret")],
    )
    capture("explicit-empty-detectors", "bob@example.com", Vault(), [], detectors=[])
    capture(
        "empty-detectors-retain-known-leak",
        mail_url + "\nbob@example.com",
        masker.vault,
        [],
        detectors=[],
    )
    result = {
        "date": "2026-10-15",
        "syntheticInputs": True,
        "python": platform.python_version(),
        "auditModuleSha256": hashlib.sha256(
            Path(sys.modules["veil.audit"].__file__).read_bytes()
        ).hexdigest(),
        "cases": rows,
        "passedCases": sum(row["expectedNewValuesMatch"] for row in rows),
        "totalCases": len(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
