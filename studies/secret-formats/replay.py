"""Replay full-token masking, restoration and actual SDK transport boundaries.

Run with --source <checkout> or in a separately installed wheel environment.
All token bodies are deterministic synthetic data. HTTPX MockTransport never
contacts a provider. Receipts store hashes and masking coverage, not token text.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

from cases import cases

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--baseline", action="store_true")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

import anthropic  # noqa: E402
import openai  # noqa: E402

from tests.sdk_wire import (  # noqa: E402
    MODEL,
    Wire,
    anthropic_message,
    chat_completion,
    http_module,
    response_object,
)
from veil import Masker, Restorer  # noqa: E402
from veil.detectors import secrets  # noqa: E402
from veil.integrations.anthropic import AnthropicVeil  # noqa: E402
from veil.integrations.openai import OpenAIVeil  # noqa: E402


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def stream_restores(masked: str, source: str, masker: Masker) -> bool:
    for size in (1, 2, 3, 7, 31):
        r = Restorer(masker.vault)
        result = (
            "".join(r.feed(masked[i : i + size]) for i in range(0, len(masked), size)) + r.flush()
        )
        if result != source:
            return False
    return True


rows = []
for c in cases():
    token = str(c["token"])
    source = f'Use "{token}" once; leave this sentence.'
    expected = 'Use "⟨SECRET_1⟩" once; leave this sentence.'
    masker = Masker()
    masked = masker.mask(source)
    entities = secrets.SecretDetector().find(source)
    row = {k: v for k, v in c.items() if k != "token"}
    row.update(
        {
            "sourceSha256": digest(source),
            "sourceCharacters": len(source),
            "maskedSha256": digest(masked),
            "maskedCharacters": len(masked),
            "fullyMasked": masked == expected,
            "wholeTokenMapping": len(masker.vault) == 1
            and masker.vault.mappings()[0].original == token,
            "restoresExactly": masker.restore(masked) == source,
            "streamRestoresExactly": stream_restores(masked, source, masker),
            "secretSpans": [
                {"start": e.span.start, "end": e.span.end, "detector": e.detector} for e in entities
            ],
        }
    )
    assert row["restoresExactly"] and row["streamRestoresExactly"]
    if not args.baseline:
        assert row["fullyMasked"] and row["wholeTokenMapping"], c["id"]
    row["sdk"] = []
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
            api_key="test", http_client=wire.client(), max_retries=0
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
        outcome = {
            "api": api,
            "fullyMaskedAtTransport": outgoing == expected,
            "requestBodySha256": digest(
                json.dumps(body, ensure_ascii=False, separators=(",", ":"))
            ),
            "restoredReplySha256": digest(reply),
            "restoresExactly": reply == source,
        }
        if not args.baseline:
            assert outcome["fullyMaskedAtTransport"], (c["id"], api)
        row["sdk"].append(outcome)
    rows.append(row)
report = {
    "python": platform.python_version(),
    "sdkVersions": {
        name: importlib.metadata.version(name)
        for name in sorted(
            {"openai", "anthropic", http_module(openai).__name__, http_module(anthropic).__name__}
        )
    },
    "secretDetectorSha256": digest(Path(secrets.__file__).read_bytes()),
    "driverSha256": digest(Path(__file__).read_bytes()),
    "casesSha256": digest(Path(__file__).with_name("cases.py").read_bytes()),
    "cases": len(rows),
    "fullyMasked": sum(r["fullyMasked"] for r in rows),
    "sdkCalls": len(rows) * 3,
    "fullyMaskedSdkCalls": sum(s["fullyMaskedAtTransport"] for r in rows for s in r["sdk"]),
    "rows": rows,
}
args.output.write_text(json.dumps(report, indent=2) + "\n")
print(
    f"{report['fullyMasked']}/{len(rows)} whole-token masks; {report['fullyMaskedSdkCalls']}/{report['sdkCalls']} fully masked SDK request bodies"
)
