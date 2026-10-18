"""Replay native authenticated HARs through the CLI and real SDK serialization."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import runpy
import subprocess
import sys
import tempfile
from contextlib import suppress
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

HERE = Path(__file__).resolve().parent


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
    from veil.integrations._common import mask_value
    from veil.integrations._json_arguments import mask_arguments, restore_arguments

    package = Path(veil.__file__).resolve().parent
    assert package.is_relative_to(args.src.resolve() if args.src else Path(sys.prefix).resolve())
    oracle = json.loads((HERE / "fixtures/oracle.json").read_text())
    capture = (
        runpy.run_path(str(HERE.parent / "http-authorization/sdk_tools.py"))["sdk_tool_capture"]
        if args.sdk
        else None
    )

    def sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    rows, sdk = [], []
    with tempfile.TemporaryDirectory(prefix="veil-har-auth-") as work:
        for record in oracle["rows"]:
            path = HERE / "fixtures" / record["file"]
            assert sha(path.read_bytes()) == record["sha256"]
            source = path.read_text()
            document = json.loads(source)
            expected = copy.deepcopy(document)
            for index, surface in enumerate(record["surfaces"], 1):
                parts = surface["path"].split("/")[1:]
                parent = expected
                for part in parts[:-1]:
                    parent = parent[int(part)] if isinstance(parent, list) else parent[part]
                scheme, credential = surface["value"].split(" ", 1)
                assert credential in oracle["credentials"].values()
                assert parent[parts[-1]] == surface["value"]
                parent[parts[-1]] = f"{scheme} ⟨SECRET_{index}⟩"

            for mode in ["text", "arguments", "typed"]:
                masker = Masker()
                if mode == "typed":
                    masked_data = mask_value(document, masker)
                    masked = json.dumps(masked_data, ensure_ascii=False)
                    restored_data = json.loads(restore_arguments(masked, masker))
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
                    restored_data = json.loads(restored)
                    assert restored == source
                assert restored_data == document
                assert json.loads(source) == document
                if mode == "text":
                    assert masker.restore(masked) == source
                    restorer = Restorer(masker.vault)
                    assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source
                    vault_path = Path(work) / (record["engine"] + ".json")
                    env = {**os.environ, "PYTHONPATH": str(package.parent)}
                    cli = subprocess.run(
                        [sys.executable, "-m", "veil.cli", "mask", "--vault", str(vault_path)],
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
                            str(vault_path),
                        ],
                        input=masked,
                        text=True,
                        capture_output=True,
                        check=True,
                        env=env,
                    )
                    assert restored_cli.stdout == source + "\n"
                rows.append(
                    {
                        "engine": record["engine"],
                        "mode": mode,
                        "correct": masked_data == expected,
                        "remainingCredentials": {
                            name: masked.count(value)
                            for name, value in oracle["credentials"].items()
                        },
                        "restoresOriginalData": True,
                        "masked": masked,
                        "vault": json.loads(masker.vault.to_json()),
                    }
                )
            if capture:
                for api in ["chat", "responses", "anthropic"]:
                    for asynchronous in [False, True]:
                        for streaming in [False, True]:
                            for tool_reply in [False, True]:
                                outcome = capture(
                                    api,
                                    asynchronous,
                                    streaming,
                                    source=source,
                                    expected=json.dumps(expected, ensure_ascii=False),
                                    tool_reply=tool_reply,
                                    assert_roundtrip=False,
                                )
                                sdk.append(
                                    {
                                        "engine": record["engine"],
                                        "api": api,
                                        "async": asynchronous,
                                        "stream": streaming,
                                        "toolReply": tool_reply,
                                        "correct": outcome["correct"],
                                        "restoresOriginalData": outcome["restoresExactly"],
                                        "callerInputUnchanged": outcome["callerInputUnchanged"],
                                        "outgoingSha256": sha(
                                            outcome["outgoingArguments"].encode()
                                        ),
                                    }
                                )
    packages = {}
    for name in ["veil-pii", "openai", "anthropic"]:
        with suppress(PackageNotFoundError):
            packages[name] = version(name)
    result = {
        "scope": __doc__,
        "python": platform.python_version(),
        "packages": packages,
        "sourceHashes": {
            str(p.relative_to(package)): sha(p.read_bytes()) for p in sorted(package.rglob("*.py"))
        },
        "oracleSha256": sha((HERE / "fixtures/oracle.json").read_bytes()),
        "directFailures": sum(not row["correct"] for row in rows),
        "sdkFailures": sum(not row["correct"] for row in sdk),
        "rows": rows,
        "sdk": sdk,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["python", "directFailures", "sdkFailures"]}))
    if not args.observe_only:
        assert result["directFailures"] == result["sdkFailures"] == 0
        assert all(row["restoresOriginalData"] and row["callerInputUnchanged"] for row in sdk)


if __name__ == "__main__":
    main()
