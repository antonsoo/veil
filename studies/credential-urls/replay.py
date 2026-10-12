"""Exercise real detection, masking, CLI vaults, streams and optional SDK transport.

Run with --source <checkout>, or with the Python from an installed wheel's venv.
--baseline records misses without accepting restoration failures. --sdk uses
the real OpenAI/Anthropic clients with a local echo transport (no API calls).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--baseline", action="store_true")
parser.add_argument("--sdk", action="store_true")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
env = dict(os.environ)
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))
    env["PYTHONPATH"] = str(args.source.resolve() / "src")
else:
    env.pop("PYTHONPATH", None)

from veil import Masker, Restorer  # noqa: E402
from veil.detectors import url as detector_module  # noqa: E402


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def cli(*command: str, text: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "veil.cli", *command],
        input=text,
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    assert result.stderr == "", result.stderr
    return result.stdout


def sdk_roundtrip(source: str, expected: str) -> list[dict[str, object]]:
    import anthropic
    import openai

    sys.path.insert(0, str(root))
    from tests.sdk_wire import MODEL, Wire, anthropic_message, chat_completion, response_object
    from veil.integrations.anthropic import AnthropicVeil
    from veil.integrations.openai import OpenAIVeil

    outcomes = []
    for api in ("chat", "responses", "anthropic"):
        sdk = anthropic if api == "anthropic" else openai

        def echo(body, api=api):
            if api == "responses":
                return response_object("completed", body["input"])
            text = body["messages"][0]["content"]
            return (
                anthropic_message([{"type": "text", "text": text}])
                if api == "anthropic"
                else chat_completion(text)
            )

        wire = Wire(sdk, echo)
        client = (sdk.Anthropic if api == "anthropic" else sdk.OpenAI)(
            api_key="test",
            http_client=wire.client(),
            max_retries=0,
        )
        wrapped = (AnthropicVeil if api == "anthropic" else OpenAIVeil)(client)
        try:
            if api == "responses":
                reply = wrapped.create_response(model=MODEL, input=source).output[0].content[0].text
            elif api == "anthropic":
                reply = (
                    wrapped.create(
                        model=MODEL, max_tokens=64, messages=[{"role": "user", "content": source}]
                    )
                    .content[0]
                    .text
                )
            else:
                reply = (
                    wrapped.create(model=MODEL, messages=[{"role": "user", "content": source}])
                    .choices[0]
                    .message.content
                )
        finally:
            client.close()
        assert len(wire.requests) == 1
        body = wire.requests[0]
        outgoing = body["input"] if api == "responses" else body["messages"][0]["content"]
        assert reply == source
        outcomes.append(
            {
                "api": api,
                "expectedAtTransport": outgoing == expected,
                "requestSha256": digest(json.dumps(body, ensure_ascii=False, sort_keys=True)),
                "restoresExactly": reply == source,
            }
        )
    return outcomes


cases_path = Path(__file__).with_name("cases.json")
rows = []
with tempfile.TemporaryDirectory(prefix="veil-synthetic-urls-") as directory:
    for case in json.loads(cases_path.read_text())["cases"]:
        url = case["url"]
        source = f'Use "{url}" once.\n'
        expected = 'Use "⟨URL_CREDENTIAL_1⟩" once.\n' if case["mask"] else source
        masker = Masker()
        masked = masker.mask(source)
        detections = detector_module.UrlCredentialDetector().find(source)
        wanted_spans = [[5, 5 + len(url)]] if case["mask"] else []
        spans = [[e.span.start, e.span.end] for e in detections]
        assert all(source[e.span.start : e.span.end] == e.value for e in detections)
        assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
        for size in (1, 2, 7, 31):
            restorer = Restorer(masker.vault)
            restored = "".join(
                restorer.feed(masked[i : i + size]) for i in range(0, len(masked), size)
            )
            assert restored + restorer.flush() == source
        vault_file = Path(directory) / f"{case['id']}.json"
        cli_masked = cli("mask", "--vault", str(vault_file), text=source)
        cli_restored = cli("restore", "--exact", "--vault", str(vault_file), text=cli_masked)
        assert cli_restored == source
        originals = [m["original"] for m in json.loads(vault_file.read_text())["mappings"]]
        row = {
            "id": case["id"],
            "mask": case["mask"],
            "sourceSha256": digest(source),
            "expectedDetection": spans == wanted_spans,
            "spans": spans,
            "expectedMask": masked == expected,
            "unchanged": masked == source,
            "maskedSha256": digest(masked),
            "restoresExactly": True,
            "streamRestoresExactly": True,
            "cliExpectedMask": cli_masked == expected,
            "cliExpectedMapping": originals == ([url] if case["mask"] else []),
            "cliRestoresExactly": True,
            "sdk": sdk_roundtrip(source, expected) if args.sdk else [],
        }
        rows.append(row)
        if not args.baseline:
            assert all(
                row[k]
                for k in (
                    "expectedDetection",
                    "expectedMask",
                    "cliExpectedMask",
                    "cliExpectedMapping",
                )
            ), row
            assert all(s["expectedAtTransport"] for s in row["sdk"]), row

report = {
    "python": platform.python_version(),
    "detectorSha256": digest(Path(detector_module.__file__).read_bytes()),
    "driverSha256": digest(Path(__file__).read_bytes()),
    "casesSha256": digest(cases_path.read_bytes()),
    "sdkVersions": {name: importlib.metadata.version(name) for name in ("openai", "anthropic")}
    if args.sdk
    else {},
    "cases": len(rows),
    "credentials": sum(r["mask"] for r in rows),
    "expectedMasks": sum(r["expectedMask"] for r in rows),
    "credentialMasks": sum(r["mask"] and r["expectedMask"] for r in rows),
    "unchangedCredentials": sum(r["mask"] and r["unchanged"] for r in rows),
    "cliExpectedMasks": sum(r["cliExpectedMask"] for r in rows),
    "sdkCalls": sum(len(r["sdk"]) for r in rows),
    "sdkExpectedMasks": sum(s["expectedAtTransport"] for r in rows for s in r["sdk"]),
    "rows": rows,
}
args.output.write_text(json.dumps(report, indent=2) + "\n")
print(
    f"{report['credentialMasks']}/{report['credentials']} complete credential masks; "
    f"{report['expectedMasks']}/{len(rows)} expected results; "
    f"{report['sdkExpectedMasks']}/{report['sdkCalls']} expected SDK requests; all restore exactly"
)
