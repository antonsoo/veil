"""Command-line interface: ``veil mask``, ``veil restore``, ``veil audit``.

Reads from a file or stdin (``-``), writes to stdout, so it composes with
pipes: ``cat ticket.txt | veil mask --vault v.json | llm-call | veil
restore --vault v.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from veil.audit import audit
from veil.masker import Masker
from veil.restore import restore_exact, restore_tolerant
from veil.vault import Vault, VaultError


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def _cmd_mask(args: argparse.Namespace) -> int:
    text = _read_input(args.input)
    vault = Vault.load(args.vault) if args.vault and _exists(args.vault) else Vault()
    masker = Masker(vault=vault)
    masked = masker.mask(text)
    sys.stdout.write(masked)
    if not masked.endswith("\n"):
        sys.stdout.write("\n")
    if args.vault:
        vault.save(args.vault)
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    text = _read_input(args.input)
    try:
        vault = Vault.load(args.vault)
    except (FileNotFoundError, VaultError) as exc:
        print(f"veil restore: {exc}", file=sys.stderr)
        return 1
    restored = restore_exact(text, vault) if args.exact else restore_tolerant(text, vault)
    sys.stdout.write(restored)
    if not restored.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    text = _read_input(args.input)
    try:
        vault = Vault.load(args.vault)
    except (FileNotFoundError, VaultError) as exc:
        print(f"veil audit: {exc}", file=sys.stderr)
        return 1
    findings = audit(text, vault)
    if args.json:
        payload = [
            {
                "kind": f.kind,
                "type": f.entity.type.value,
                "value": f.entity.value,
                "start": f.entity.span.start,
                "end": f.entity.span.end,
                "detector": f.entity.detector,
            }
            for f in findings
        ]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if not findings:
            print("veil audit: no leaks found")
        for f in findings:
            print(f"[{f.kind}] {f.entity.type.value} {f.entity.value!r} @ {f.entity.span.start}")
    return 1 if findings else 0


def _exists(path: str) -> bool:
    return os.path.exists(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veil", description="Reversible PII masking for LLM calls."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_mask = sub.add_parser("mask", help="Mask PII in a file or stdin.")
    p_mask.add_argument("input", help="Input file path, or '-' for stdin.")
    p_mask.add_argument("--vault", required=True, help="Vault JSON path (created/updated).")
    p_mask.set_defaults(func=_cmd_mask)

    p_restore = sub.add_parser("restore", help="Restore PII from surrogates using a vault.")
    p_restore.add_argument("input", help="Input file path, or '-' for stdin.")
    p_restore.add_argument("--vault", required=True, help="Vault JSON path (must exist).")
    p_restore.add_argument(
        "--exact",
        action="store_true",
        help="Exact matching only (skip tolerant case/possessive pass).",
    )
    p_restore.set_defaults(func=_cmd_restore)

    p_audit = sub.add_parser("audit", help="Check text for leaked originals or new PII.")
    p_audit.add_argument("input", help="Input file path, or '-' for stdin.")
    p_audit.add_argument("--vault", required=True, help="Vault JSON path (must exist).")
    p_audit.add_argument("--json", action="store_true", help="Emit findings as JSON.")
    p_audit.set_defaults(func=_cmd_audit)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
