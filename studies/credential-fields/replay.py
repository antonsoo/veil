"""Core, CLI, incremental restoration and actual SDK wire replay; synthetic data."""

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

import veil
from veil import Masker, Restorer

HERE = Path(__file__).resolve().parent
RAW = r'{ "literal":"⟨SECRET_1⟩", "credentials":{"passw\u006frd":"river stone", "apiKey":"deadbeef", "client_secret":"say \"hello\"\nagain"}, "password":"repeat", "password":"repeat", "access_token":["ordinary"], "refresh_token":{"value":"ordinary"}, "count":9007199254740993, "count":1.2300e+40, "ordinary":"plain prose" }'
EXPECTED = (
    RAW.replace('"river stone"', '"⟨SECRET_2⟩"', 1)
    .replace('"deadbeef"', '"⟨SECRET_3⟩"')
    .replace(r'"say \"hello\"\nagain"', '"⟨SECRET_4⟩"')
    .replace('"repeat"', '"⟨SECRET_5⟩"')
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sdk", action="store_true")
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    fixtures = json.loads((HERE / "cases.json").read_text())
    assert runpy.run_path(str(HERE / "fixtures.py"))["cases"]() == fixtures["cases"]
    rows = []
    with tempfile.TemporaryDirectory(prefix="veil-credential-fields-") as directory:
        for case in fixtures["cases"]:
            source = case["source"]
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
                    **case,
                    "masked": masked,
                    "correct": masked == case["expected"],
                    "mappings": [
                        {"original": m.original, "surrogate": m.surrogate, "detector": m.first_seen}
                        for m in masker.vault.mappings()
                    ],
                    "exactCLIAndStreamRestore": True,
                }
            )
    captures = []
    tools = []
    if args.sdk:
        capture = runpy.run_path(str(HERE.parent / "email-boundaries/replay.py"))["sdk_capture"]
        # A realistic support paste rather than a catalogue of independent probes.
        source = 'Failed local integration.\n{"password":"river stone","client_secret":"local-secret"}\nAPI_KEY=small-key\nx-api-key: header-token\nKeep the status code and field names.'
        expected = (
            source.replace("river stone", "⟨SECRET_1⟩")
            .replace("local-secret", "⟨SECRET_2⟩")
            .replace("small-key", "⟨SECRET_3⟩")
            .replace("header-token", "⟨SECRET_4⟩")
        )
        capture_tool = runpy.run_path(str(HERE.parent / "http-authorization/sdk_tools.py"))[
            "sdk_tool_capture"
        ]
        for api in ("chat", "responses", "anthropic"):
            for asynchronous in (False, True):
                for streaming in (False, True):
                    row = capture(source, api, asynchronous, streaming)
                    row["correct"] = row["outgoing"] == expected
                    captures.append(row)
                    tools.append(
                        capture_tool(
                            api,
                            asynchronous,
                            streaming,
                            source=RAW,
                            expected=EXPECTED,
                            tool_reply=True,
                        )
                    )
    root = Path(veil.__file__).parent
    report = {
        "provenance": __doc__,
        "python": sys.version.split()[0],
        "versions": {name: version(name) for name in (("openai", "anthropic") if args.sdk else ())},
        "runtimeFiles": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")
        },
        "cases": rows,
        "sdk": captures,
        "sdkTools": tools,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{sum(r['correct'] for r in rows)}/{len(rows)} raw cases; {sum(r['correct'] for r in captures)}/{len(captures)} SDK text; {sum(r['correct'] for r in tools)}/{len(tools)} SDK tools; exact CLI/stream restoration retained"
    )
    if args.require_fixed:
        assert all(r["correct"] for r in rows + captures + tools)
        assert all(r["unrelatedSyntaxPreserved"] for r in tools)


if __name__ == "__main__":
    main()
