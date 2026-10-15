"""Replay exact leak checks against controlled, varied-length vaults.

Run with the baseline or corrected installed Python environment. No network or
provider SDK is involved. All identities and credential URLs are synthetic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import veil
from veil.audit import find_leaked_originals
from veil.detectors.email import EmailDetector
from veil.detectors.url import UrlCredentialDetector
from veil.masker import Masker
from veil.surrogates import PlaceholderSurrogates
from veil.types import EntityType
from veil.vault import Vault


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def observed(findings: Any) -> list[tuple[str, str, int, int]]:
    return [
        (f.entity.type.value, f.entity.value, f.entity.span.start, f.entity.span.end)
        for f in findings
    ]


def oracle(text: str, vault: Vault) -> list[tuple[str, str, int, int]]:
    # Native search per mapping is an independent definition of this API's
    # nonoverlap policy. Different originals can overlap; one original cannot.
    hits = []
    for order, mapping in enumerate(vault.mappings()):
        at = text.find(mapping.original)
        while at >= 0:
            stop = at + len(mapping.original)
            hits.append((at, order, mapping.type.value, mapping.original, stop))
            at = text.find(mapping.original, stop)
    return [(kind, value, at, stop) for at, _, kind, value, stop in sorted(hits)]


def receipt(rows: list[tuple[str, str, int, int]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "sha256": digest(json.dumps(rows, ensure_ascii=False, separators=(",", ":"))),
        "occurrences": [
            {"type": kind, "valueSha256": digest(value), "start": at, "end": stop}
            for kind, value, at, stop in rows
        ],
    }


def cli(text: str, vault: Vault) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="veil-leak-audit-") as directory:
        root = Path(directory)
        (root / "outgoing.txt").write_text(text)
        vault.save(str(root / "vault.json"))
        started = time.perf_counter()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "veil.cli",
                "audit",
                str(root / "outgoing.txt"),
                "--vault",
                str(root / "vault.json"),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        elapsed = time.perf_counter() - started
        assert result.stderr == "", result.stderr
        payload = json.loads(result.stdout)
        assert all(row["kind"] == "leaked_original" for row in payload), payload
        rows = [(r["type"], r["value"], r["start"], r["end"]) for r in payload]
        assert rows == oracle(text, vault)
        assert result.returncode == (1 if rows else 0)
        return {"seconds": elapsed, "exitCode": result.returncode, **receipt(rows)}


def run_case(name: str, text: str, masker: Masker, *, with_cli: bool) -> dict[str, Any]:
    expected = oracle(text, masker.vault)
    started = time.perf_counter()
    cold = observed(find_leaked_originals(text, masker.vault))
    cold_seconds = time.perf_counter() - started
    started = time.perf_counter()
    warm = observed(find_leaked_originals(text, masker.vault))
    warm_seconds = time.perf_counter() - started
    assert cold == warm == expected
    result = {
        "case": name,
        "inputChars": len(text),
        "inputBytes": len(text.encode()),
        "inputSha256": digest(text),
        "mappings": len(masker.vault),
        "distinctLengths": len({len(m.original) for m in masker.vault.mappings()}),
        "coldSeconds": cold_seconds,
        "warmSeconds": warm_seconds,
        "exactOracleMatch": True,
        **receipt(cold),
    }
    if with_cli:
        result["cli"] = cli(text, masker.vault)
    print(
        f"{name}: {len(text):,} chars; {len(masker.vault):,} mappings; "
        f"cold {cold_seconds:.3f}s, warm {warm_seconds:.3f}s; {len(cold)} exact findings",
        flush=True,
    )
    return result


def save(output: Path, cases: list[dict[str, Any]]) -> None:
    result = {
        "date": "2026-10-15",
        "controlledSyntheticInputs": True,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "veilVersion": veil.__version__,
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


def same_length_control() -> dict[str, Any]:
    prefix = "https://files.example.test/shared/archive/"
    urls = [f"{prefix}{i:06d}?token=synthetic-key-{i:06d}" for i in range(1000)]
    masker = Masker(detectors=[UrlCredentialDetector()])
    masker.mask_many(urls)
    text = "\n".join(f"{prefix}public-{i:06d}" for i in range(10_000))
    return run_case("same-length-shared-prefix", text + "\n" + urls[-1], masker, with_cli=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix-control-only", action="store_true")
    args = parser.parse_args()
    if args.prefix_control_only:
        save(args.output, [same_length_control()])
        return
    # Benign repeated prose deliberately has the same first letters as the
    # stored values. This is a scale experiment, not recorded model output.
    sentence = (
        "The archive contains the project history and the review notes. "
        "Each chapter has the changes that the author checked, with the "
        "reason for the change and the result of the review.\n"
    )
    prose = sentence * 1000
    urls = [
        f"https://files.example.test/{i}/{'q' * i}?token=synthetic-private-value"
        for i in range(1, 3001)
    ]
    masker = Masker(detectors=[UrlCredentialDetector()])
    masked = masker.mask_many(urls)
    assert len(masker.vault) == len(urls)
    assert all(
        masker.restore(value, tolerant=False) == source
        for source, value in zip(urls, masked, strict=True)
    )
    cases = [run_case("varied-urls-clean", prose, masker, with_cli=True)]
    # Use a freshly loaded vault so both cases include building the lookup.
    masker = Masker(vault=Vault.from_json(masker.vault.to_json()))
    cases.append(
        run_case("varied-urls-leak", prose + urls[-1] + "\n" + urls[9], masker, with_cli=True)
    )

    emails = [f"user{i:05d}@customer.example.test" for i in range(10_000)]
    masker = Masker(detectors=[EmailDetector()])
    masker.mask_many(emails)
    assert len(masker.vault) == len(emails)
    cases.append(run_case("same-length-emails", prose + emails[-1], masker, with_cli=False))

    prefix = "https://files.example.test/" + "shared-folder/" * 20
    shared = [f"{prefix}{'q' * i}?token=synthetic-{i}" for i in range(1, 1001)]
    masker = Masker(detectors=[UrlCredentialDetector()])
    masker.mask_many(shared)
    cases.append(
        run_case(
            "shared-prefix-urls", prose + prefix + "no-token\n" + shared[-1], masker, with_cli=False
        )
    )

    # Long nested originals, Unicode offsets, equal originals in two entity
    # types and repeated overlaps must retain the established exact semantics.
    vault = Vault()
    generator = PlaceholderSurrogates()
    for kind, value in [
        (EntityType.PERSON, "a"),
        (EntityType.PERSON, "aa"),
        (EntityType.PERSON, "a" * 31),
        (EntityType.PERSON, "a" * 32),
        (EntityType.ORG, "a" * 32),
        (EntityType.PERSON, "a" * 33),
        (EntityType.PERSON, "a" * 65),
        (EntityType.PERSON, "💬é" * 20),
    ]:
        vault.get_or_create(kind, value, generator)
    cases.append(
        run_case(
            "overlap-and-unicode",
            "💬" + "a" * 100 + " " + "💬é" * 30,
            Masker(vault=vault),
            with_cli=False,
        )
    )
    # A cached index must track additions and transaction rollback.
    vault = Vault()
    assert find_leaked_originals("Added name", vault) == []
    vault.get_or_create(EntityType.PERSON, "Added name", generator)
    assert len(find_leaked_originals("Added name", vault)) == 1
    try:
        with vault._transaction():
            vault.get_or_create(EntityType.PERSON, "Rolled back", generator)
            assert len(find_leaked_originals("Rolled back", vault)) == 1
            raise ValueError("controlled rollback")
    except ValueError:
        pass
    assert find_leaked_originals("Rolled back", vault) == []
    cases.append(same_length_control())
    save(args.output, cases)


if __name__ == "__main__":
    main()
