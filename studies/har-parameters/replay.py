"""Replay real browser/proxy HAR fields through masking, CLI and SDK transports.

Provider replies are authored loopback echoes over MockTransport. No model API
is called, and SDK serialization does not establish provider acceptance.
Echoes use tool-argument channels, whose JSON escaping is defined. Ordinary
assistant text is plaintext and does not promise a serialized JSON round trip.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import re
import runpy
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

HERE = Path(__file__).resolve().parent
TOKEN = re.compile(r"⟨(?:SECRET|URL_CREDENTIAL)_\d+⟩")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pointed(document: Any, path: str) -> Any:
    for key in path.strip("/").split("/"):
        document = document[int(key)] if isinstance(document, list) else document[key]
    return document


def uncovered(document: Any, surfaces: list[dict[str, Any]]) -> list[str]:
    exposed = []
    for surface in surfaces:
        value = pointed(document, surface["path"])
        if TOKEN.fullmatch(value):
            continue
        if surface["path"].endswith("/url"):
            remaining = {v for _, v in parse_qsl(urlsplit(value).query)}
        elif surface["path"].endswith("/postData/text"):
            if surface["source"].startswith("--"):
                # These retained authored fields have single-line values. Match
                # complete MIME value lines, not incidental letters in headers
                # such as the 'cat' inside 'application'. No MIME parser from
                # the implementation is used as this exposure oracle.
                remaining = {v for v in surface["values"] if "\r\n" + v + "\r\n" in value}
            else:
                remaining = {v for _, v in parse_qsl(value)}
        else:
            remaining = {v for v in surface["values"] if v in value}
        if remaining.intersection(surface["values"]):
            exposed.append(surface["path"])
    return exposed


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
    from veil.integrations._common import mask_value, restore_value
    from veil.integrations._json_arguments import mask_arguments, restore_arguments

    package = Path(veil.__file__).resolve().parent
    assert package.is_relative_to(args.src.resolve() if args.src else Path(sys.prefix).resolve())
    oracle = json.loads((HERE / "fixtures/oracle.json").read_text())
    capture = (
        runpy.run_path(str(HERE.parent / "http-authorization/sdk_tools.py"))["sdk_tool_capture"]
        if args.sdk
        else None
    )
    args.out.mkdir(parents=True, exist_ok=True)
    rows, sdk = [], []
    with tempfile.TemporaryDirectory(prefix="veil-har-params-") as work:
        for item in oracle["rows"]:
            raw = (HERE / "fixtures" / item["file"]).read_bytes()
            assert sha(raw) == item["sha256"]
            source = raw.decode()
            document = json.loads(source)
            original = copy.deepcopy(document)
            for surface in item["surfaces"]:
                assert pointed(document, surface["path"]) == surface["source"]
            for mode in ["text", "arguments", "typed"]:
                masker = Masker()
                if mode == "typed":
                    masked_data = mask_value(document, masker)
                    masked = json.dumps(masked_data, ensure_ascii=False)
                    assert restore_value(masked_data, masker) == document
                else:
                    masked = (
                        masker.mask(source) if mode == "text" else mask_arguments(source, masker)
                    )
                    masked_data = json.loads(masked)
                    restored = (
                        masker.restore(masked, tolerant=False)
                        if mode == "text"
                        else restore_arguments(masked, masker)
                    )
                    assert restored == source
                assert document == original
                if mode == "text":
                    restorer = Restorer(masker.vault)
                    assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source
                    vault = Path(work) / (item["engine"] + ".json")
                    env = {**os.environ, "PYTHONPATH": str(package.parent)}
                    cli = subprocess.run(
                        [sys.executable, "-m", "veil.cli", "mask", "--vault", str(vault)],
                        input=source,
                        text=True,
                        capture_output=True,
                        check=True,
                        env=env,
                    )
                    assert cli.stdout == masked + "\n"
                    restored_cli = subprocess.run(
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
                    assert restored_cli.stdout == source + "\n"
                    (args.out / (item["engine"] + ".masked.har")).write_text(masked)
                    (args.out / (item["engine"] + ".vault.json")).write_text(masker.vault.to_json())
                # Ordinary query/parameter values remain useful outside opaque
                # serialized containers. They never acquire credential context.
                for before, after in zip(
                    document["log"]["entries"], masked_data["log"]["entries"], strict=True
                ):
                    for kind in ["queryString", "params"]:
                        left = (
                            before["request"]
                            if kind == "queryString"
                            else before["request"].get("postData", {})
                        )
                        right = (
                            after["request"]
                            if kind == "queryString"
                            else after["request"].get("postData", {})
                        )
                        for a, b in zip(left.get(kind, []), right.get(kind, []), strict=True):
                            if a["name"] == "format":
                                assert b == a
                rows.append(
                    {
                        "engine": item["engine"],
                        "mode": mode,
                        "sourceSha256": item["sha256"],
                        "maskedSha256": sha(masked.encode()),
                        "credentialSurfaces": len(item["surfaces"]),
                        "uncovered": uncovered(masked_data, item["surfaces"]),
                        "restoredOriginal": True,
                        "callerInputUnchanged": True,
                        "publicParameterRetained": True,
                    }
                )
            if capture:
                for api in ["chat", "responses", "anthropic"]:
                    for asynchronous in [False, True]:
                        for streaming in [False, True]:
                            outcome = capture(
                                api,
                                asynchronous,
                                streaming,
                                source=source,
                                expected=source,
                                tool_reply=True,
                                assert_roundtrip=False,
                            )
                            assert outcome["restoresExactly"] and outcome["callerInputUnchanged"]
                            sdk.append(
                                {
                                    "engine": item["engine"],
                                    "api": api,
                                    "async": asynchronous,
                                    "stream": streaming,
                                    "toolReply": True,
                                    "uncovered": uncovered(
                                        json.loads(outcome["outgoingArguments"]), item["surfaces"]
                                    ),
                                    "outgoingSha256": sha(outcome["outgoingArguments"].encode()),
                                    "restoredOriginal": True,
                                    "callerInputUnchanged": True,
                                }
                            )
    result = {
        "scope": __doc__,
        "python": platform.python_version(),
        "packages": {
            name: version(name)
            for name in (["veil-pii", "anthropic", "openai"] if args.sdk else ["veil-pii"])
        },
        "oracleSha256": sha((HERE / "fixtures/oracle.json").read_bytes()),
        "sourceHashes": {
            str(p.relative_to(package)): sha(p.read_bytes()) for p in sorted(package.rglob("*.py"))
        },
        "directFailures": sum(bool(row["uncovered"]) for row in rows),
        "sdkFailures": sum(bool(row["uncovered"]) for row in sdk),
        "rows": rows,
        "sdk": sdk,
    }
    (args.out / "replay.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ["python", "directFailures", "sdkFailures"]}))
    if not args.observe_only:
        assert result["directFailures"] == result["sdkFailures"] == 0


if __name__ == "__main__":
    main()
