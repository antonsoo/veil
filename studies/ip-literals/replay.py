"""Replay complete spans, restoration and real CLI text/JSON/JSONL round trips.

--source selects a source checkout; omit it to exercise an installed wheel.
--baseline records misses but never accepts a failed restoration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
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
env = dict(os.environ)
if args.source:
    source_path = str(args.source.resolve() / "src")
    sys.path.insert(0, source_path)
    env["PYTHONPATH"] = source_path
else:
    env.pop("PYTHONPATH", None)
from veil import Masker, Restorer  # noqa: E402
from veil.detectors.ip import IpDetector  # noqa: E402


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def expected_mask(text: str, case: dict) -> str:
    return text.replace(case["literal"], "⟨IPV6_1⟩") if case["mask"] else text


root = Path(__file__).resolve().parents[2]


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


cases = json.loads(Path(__file__).with_name("cases.json").read_text())["cases"]
rows = []
for case in cases:
    literal = case["literal"]
    if case["mask"]:
        assert (
            socket.inet_pton(socket.AF_INET6, literal.partition("%")[0]).hex()
            == case["nativeAddressHex"]
        )
    text = case["prefix"] + literal + case["suffix"]
    found = IpDetector().find(text)
    expected = (
        [["IPV6", literal, len(case["prefix"]), len(case["prefix"]) + len(literal)]]
        if case["mask"]
        else []
    )
    actual = [[e.type.value, e.value, e.span.start, e.span.end] for e in found]
    assert all(text[e.span.start : e.span.end] == e.value for e in found)
    masker = Masker()
    masked = masker.mask(text)
    assert masker.restore(masked, tolerant=False) == text
    for chunk in (1, 2, 7, 31):
        restorer = Restorer(masker.vault)
        restored = "".join(
            restorer.feed(masked[i : i + chunk]) for i in range(0, len(masked), chunk)
        )
        assert restored + restorer.flush() == text
    row = {
        "id": case["id"],
        "expectedSpans": actual == expected,
        "expectedMask": masked == expected_mask(text, case),
        "restoresExactly": True,
        "masked": masked,
    }
    if not args.baseline:
        assert row["expectedSpans"] and row["expectedMask"], row
    rows.append(row)

# These are text files containing JSON/JSONL, not a special CLI structured mode.
# Exercise actual stdin, file output, vault loading and restoring in fresh processes.
sdk_rows = []
if args.sdk:
    for case in [c for c in cases if c["id"].startswith("regression-")]:
        text = "peer=" + case["literal"] + "\n"
        for outcome in sdk_roundtrip(text, expected_mask(text, case)):
            if not args.baseline:
                assert outcome["expectedAtTransport"], (case, outcome)
            sdk_rows.append({"id": case["id"], **outcome})

cli_rows = []
with tempfile.TemporaryDirectory(prefix="veil-ip-literals-") as directory:
    for case in [c for c in cases if c["id"].startswith("regression-")]:
        for kind in ("text", "json", "jsonl"):
            payload = {"peer": case["literal"], "message": "retry"}
            text = (
                "peer=" + case["literal"] + "\r\n" if kind == "text" else json.dumps(payload) + "\n"
            )
            if kind == "jsonl":
                text += json.dumps({"message": "unchanged"}) + "\n"
            vault = str(Path(directory) / f"{case['id']}-{kind}-vault.json")
            output = str(Path(directory) / "masked.txt")
            command = [sys.executable, "-m", "veil.cli"]
            mask_run = subprocess.run(
                command + ["mask", "--vault", vault, "--output", output],
                input=text.encode(),
                capture_output=True,
                check=True,
                env=env,
            )
            assert mask_run.stdout == mask_run.stderr == b""
            masked = Path(output).read_bytes().decode()
            restore_run = subprocess.run(
                command + ["restore", output, "--vault", vault],
                capture_output=True,
                check=True,
                env=env,
            )
            assert restore_run.stderr == b"" and restore_run.stdout.decode() == text
            if kind != "text":
                for line in masked.splitlines():
                    json.loads(line)
            correct = masked == expected_mask(text, case)
            if not args.baseline:
                assert correct, (case["id"], kind, masked)
            cli_rows.append(
                {
                    "id": case["id"],
                    "format": kind,
                    "expectedMask": correct,
                    "restoresExactly": True,
                    "sourceSha256": digest(text),
                    "maskedSha256": digest(masked),
                }
            )
report = {
    "python": platform.python_version(),
    "baseline": args.baseline,
    "cases": len(rows),
    "expectedSpans": sum(r["expectedSpans"] for r in rows),
    "expectedMask": sum(r["expectedMask"] for r in rows),
    "exactRestorations": len(rows),
    "streamedRestorations": 4 * len(rows),
    "cliFlows": len(cli_rows),
    "cliExpectedMask": sum(r["expectedMask"] for r in cli_rows),
    "cliExactRestorations": len(cli_rows),
    "sdk": sdk_rows,
    "sdkRequests": len(sdk_rows),
    "sdkExpectedMask": sum(r["expectedAtTransport"] for r in sdk_rows),
    "rows": rows,
    "cli": cli_rows,
}
args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
print({k: v for k, v in report.items() if k not in ("rows", "cli", "sdk")})
