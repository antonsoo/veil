"""Command-line interface: ``veil mask``, ``veil restore``, ``veil audit``.

Reads a file, or stdin when no file is named, and writes to stdout or to
``--output``, so it composes with pipes: ``cat ticket.txt | veil mask --vault
v.json | llm-call | veil restore --vault v.json``.

Text is UTF-8 on every path, the pipes included. Python gives a pipe the
locale's encoding, which on Windows is a legacy code page that has no surrogate
brackets: ``veil mask ticket.txt > masked.txt`` stopped there with a
``UnicodeEncodeError``. Line endings are passed through as they are, so a CRLF
file is still one after masking.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from veil import __version__
from veil.audit import audit
from veil.backends.known_entities import KnownEntitiesBackend
from veil.masker import Masker
from veil.restore import restore_exact, restore_tolerant
from veil.vault import Vault, VaultError


def _utf8_pipes() -> None:
    """Read and write the standard streams as UTF-8, without translating line endings."""
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:  # a stream replaced by something that isn't a text file
            reconfigure(encoding="utf-8", newline="")


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _write_output(text: str, path: str | None) -> None:
    """The result, ending in a newline, to ``path`` or to stdout."""
    if not text.endswith("\n"):
        # A file that ends without a newline gets the kind the rest of it uses.
        text += "\r\n" if "\r\n" in text else "\n"
    if path is None:
        sys.stdout.write(text)
        return
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


_KINDS = {"person": "persons", "org": "orgs", "location": "locations"}


def _known_entities(args: argparse.Namespace) -> KnownEntitiesBackend | None:
    """The names given on the command line and in ``--names-file``.

    Patterns find what has a shape (an email address, a card number); a name has none, and
    the caller usually knows it already. A names file holds one name per line, a person's
    unless the line starts with ``org:`` or ``location:``; blank lines and ``#`` comments are
    skipped.
    """
    known: dict[str, list[str]] = {
        "persons": list(args.name or []),
        "orgs": list(args.org or []),
        "locations": list(args.location or []),
    }
    for path in args.names_file or []:
        with open(path, encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                kind, sep, rest = line.partition(":")
                if sep and kind.strip().lower() in _KINDS:
                    known[_KINDS[kind.strip().lower()]].append(rest.strip())
                else:
                    known["persons"].append(line)
    if not any(value.strip() for values in known.values() for value in values):
        return None
    return KnownEntitiesBackend(
        persons=known["persons"], orgs=known["orgs"], locations=known["locations"]
    )


def _cmd_mask(args: argparse.Namespace) -> int:
    text = _read_input(args.input)
    vault = Vault.load(args.vault) if args.vault and _exists(args.vault) else Vault()
    backend = _known_entities(args)
    masker = Masker(vault=vault, name_backends=[backend] if backend else [])
    _write_output(masker.mask(text), args.output)
    if args.vault:
        vault.save(args.vault)
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    text = _read_input(args.input)
    vault = Vault.load(args.vault)
    restored = restore_exact(text, vault) if args.exact else restore_tolerant(text, vault)
    _write_output(restored, args.output)
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    text = _read_input(args.input)
    vault = Vault.load(args.vault)
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
    parser.add_argument("--version", action="version", version=f"veil {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    input_help = "Input file (UTF-8). Without one, or with '-', stdin is read."
    output_help = "Write the result to this file (UTF-8) instead of stdout."

    p_mask = sub.add_parser("mask", help="Mask PII in a file or stdin.")
    p_mask.add_argument("input", nargs="?", default="-", help=input_help)
    p_mask.add_argument("--vault", required=True, help="Vault JSON path (created/updated).")
    p_mask.add_argument("-o", "--output", metavar="FILE", help=output_help)
    p_mask.add_argument(
        "--name",
        action="append",
        metavar="NAME",
        help="A person's name to mask, as your application knows it (repeatable). "
        "Names have no pattern to detect: give each form that may appear, "
        'e.g. --name "Jordan Alvarez" --name Jordan.',
    )
    p_mask.add_argument("--org", action="append", metavar="NAME", help="An organization's name.")
    p_mask.add_argument("--location", action="append", metavar="NAME", help="A place name.")
    p_mask.add_argument(
        "--names-file",
        action="append",
        metavar="FILE",
        help="A file of names, one per line: a person's, or 'org: ...' / 'location: ...'.",
    )
    p_mask.set_defaults(func=_cmd_mask)

    p_restore = sub.add_parser("restore", help="Restore PII from surrogates using a vault.")
    p_restore.add_argument("input", nargs="?", default="-", help=input_help)
    p_restore.add_argument("--vault", required=True, help="Vault JSON path (must exist).")
    p_restore.add_argument("-o", "--output", metavar="FILE", help=output_help)
    p_restore.add_argument(
        "--exact",
        action="store_true",
        help="Exact matching only (skip tolerant case/possessive pass).",
    )
    p_restore.set_defaults(func=_cmd_restore)

    p_audit = sub.add_parser("audit", help="Check text for leaked originals or new PII.")
    p_audit.add_argument("input", nargs="?", default="-", help=input_help)
    p_audit.add_argument("--vault", required=True, help="Vault JSON path (must exist).")
    p_audit.add_argument("--json", action="store_true", help="Emit findings as JSON.")
    p_audit.set_defaults(func=_cmd_audit)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _utf8_pipes()
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"veil {args.command}: file not found: {exc.filename}", file=sys.stderr)
        return 2
    except UnicodeDecodeError as exc:
        print(f"veil {args.command}: could not decode input as UTF-8: {exc}", file=sys.stderr)
        return 2
    except VaultError as exc:
        print(f"veil {args.command}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
