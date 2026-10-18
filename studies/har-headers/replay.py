"""Replay actual native HARs through text, CLI and real SDK serialization.

The expected cookie fields come from HAR paths, independent of Veil's tokenizer
and detectors. SDK clients use mock transports; no provider call is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import runpy
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

HERE = Path(__file__).resolve().parent


def reference(source: str) -> tuple[object, dict[str, str]]:
    document = json.loads(source)
    paths = set()
    for i, entry in enumerate(document["log"]["entries"]):
        for side in ["request", "response"]:
            for j, header in enumerate(entry[side]["headers"]):
                if header["name"].lower() in {"cookie", "set-cookie"}:
                    paths.add(("log", "entries", i, side, "headers", j, "value"))
            for j, _cookie in enumerate(entry[side]["cookies"]):
                paths.add(("log", "entries", i, side, "cookies", j, "value"))
    mappings = {}

    def visit(value, path=()):
        if path in paths and value:
            return mappings.setdefault(value, f"⟨SECRET_{len(mappings) + 1}⟩")
        if isinstance(value, dict):
            return {key: visit(child, (*path, key)) for key, child in value.items()}
        if isinstance(value, list):
            return [visit(child, (*path, i)) for i, child in enumerate(value)]
        return value

    return visit(document), mappings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observe-only", action="store_true")
    parser.add_argument("--sdk", action="store_true")
    args = parser.parse_args()
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import veil
    from veil import Masker, Restorer
    from veil.integrations._json_arguments import mask_arguments, restore_arguments

    package = Path(veil.__file__).resolve().parent
    assert package.is_relative_to(args.src.resolve() if args.src else Path(sys.prefix).resolve())
    oracle = json.loads((HERE / "fixtures/oracle.json").read_text())

    def sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    rows, sdk = [], []
    capture = (
        runpy.run_path(str(HERE.parent / "http-authorization/sdk_tools.py"))["sdk_tool_capture"]
        if args.sdk
        else None
    )
    with tempfile.TemporaryDirectory(prefix="veil-har-cli-") as work:
        for record in oracle["rows"]:
            path = HERE / "fixtures" / record["file"]
            assert sha(path.read_bytes()) == record["sha256"]
            source = path.read_text()
            expected, originals = reference(source)
            for mode in ["text", "arguments"]:
                masker = Masker()
                masked = masker.mask(source) if mode == "text" else mask_arguments(source, masker)
                restored = (
                    masker.restore(masked, tolerant=False)
                    if mode == "text"
                    else restore_arguments(masked, masker)
                )
                correct = json.loads(masked) == expected and record["session"] not in masked
                assert json.loads(restored) == json.loads(source)
                if mode == "text":
                    assert restored == source and masker.restore(masked) == source
                    restorer = Restorer(masker.vault)
                    assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source
                    vault = Path(work) / (record["engine"] + ".json")
                    env = {**os.environ, "PYTHONPATH": str(package.parent)}
                    result = subprocess.run(
                        [sys.executable, "-m", "veil.cli", "mask", "--vault", str(vault)],
                        input=source,
                        text=True,
                        capture_output=True,
                        check=True,
                        env=env,
                    )
                    assert result.stdout == masked + ("" if masked.endswith("\n") else "\n")
                    undo = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "veil.cli",
                            "restore",
                            "--exact",
                            "--vault",
                            str(vault),
                        ],
                        input=masked,
                        text=True,
                        capture_output=True,
                        check=True,
                        env=env,
                    )
                    assert undo.stdout == source + ("" if source.endswith("\n") else "\n")
                rows.append(
                    {
                        "engine": record["engine"],
                        "mode": mode,
                        "sourceSha256": record["sha256"],
                        "masked": masked,
                        "sessionOccurrences": masked.count(record["session"]),
                        "correct": correct,
                        "restoresOriginalData": True,
                        "vault": json.loads(masker.vault.to_json()),
                    }
                )
            if capture:
                expected_text = json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
                for api in ["chat", "responses", "anthropic"]:
                    for asynchronous in [False, True]:
                        for streaming in [False, True]:
                            for tool_reply in [False, True]:
                                result = capture(
                                    api,
                                    asynchronous,
                                    streaming,
                                    source=source,
                                    expected=expected_text,
                                    tool_reply=tool_reply,
                                    assert_roundtrip=False,
                                )
                                outgoing = result["outgoingArguments"]
                                sdk.append(
                                    {
                                        "engine": record["engine"],
                                        "api": api,
                                        "async": asynchronous,
                                        "stream": streaming,
                                        "toolReply": tool_reply,
                                        "correct": result["correct"]
                                        and record["session"] not in outgoing,
                                        "restoresOriginalData": result["restoresExactly"],
                                        "callerInputUnchanged": result["callerInputUnchanged"],
                                        "outgoingSha256": sha(outgoing.encode()),
                                        "requestSha256": sha(
                                            json.dumps(result["request"], sort_keys=True).encode()
                                        ),
                                        "replySha256": sha(result["reply"].encode()),
                                    }
                                )
            assert len(originals) == 5
    failures = sum(not row["correct"] for row in rows)
    sdk_failures = sum(not (row["correct"] and row["restoresOriginalData"]) for row in sdk)
    result = {
        "scope": __doc__,
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ["veil-pii", "openai", "anthropic"]},
        "oracleSha256": sha((HERE / "fixtures/oracle.json").read_bytes()),
        "sourceHashes": {
            str(p.relative_to(package)): sha(p.read_bytes()) for p in sorted(package.rglob("*.py"))
        },
        "directFailures": failures,
        "sdkFailures": sdk_failures,
        "direct": rows,
        "sdk": sdk,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        f"4 native text/argument forms + {len(sdk)} SDK paths: {failures} / {sdk_failures} unexpected results"
    )
    if not args.observe_only:
        assert failures == sdk_failures == 0


if __name__ == "__main__":
    main()
