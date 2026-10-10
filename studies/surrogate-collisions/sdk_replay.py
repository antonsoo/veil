"""Capture actual SDK request/response objects over a local echo transport.

Uses tests/sdk_wire.py for the provider wire envelopes. No key or model call.
The bodies, masking decisions and restored replies are retained for inspection.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--label", default="checkout")
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

import anthropic  # noqa: E402
import openai  # noqa: E402

from tests.sdk_wire import (  # noqa: E402
    MODEL,
    Wire,
    anthropic_message,
    chat_completion,
    response_object,
)
from veil import Masker, RealisticSurrogates, VaultError  # noqa: E402
from veil.integrations.anthropic import AnthropicVeil  # noqa: E402
from veil.integrations.openai import OpenAIVeil  # noqa: E402

results = []
for api in ["anthropic", "chat", "responses"]:
    for case in ["literal-in-text", "literal-in-later-field", "original-in-later-field"]:
        sdk = anthropic if api == "anthropic" else openai

        def echoed(body, api=api):
            if api == "responses":
                return response_object("completed", body["input"])
            text = body["messages"][0]["content"]
            return (
                anthropic_message([{"type": "text", "text": text}])
                if api == "anthropic"
                else chat_completion(text)
            )

        wire = Wire(sdk, echoed)
        raw_client = (sdk.Anthropic if api == "anthropic" else sdk.OpenAI)(
            api_key="test",
            http_client=wire.client(),
            max_retries=0,
        )
        masker = (
            Masker(surrogate_generator=RealisticSurrogates())
            if case.startswith("original")
            else Masker()
        )
        wrapped = (AnthropicVeil if api == "anthropic" else OpenAIVeil)(raw_client, masker=masker)
        text = (
            "Contact alice@example.org; literal ⟨email_1⟩"
            if case == "literal-in-text"
            else "alice@example.org"
        )
        later = "user1@example.org" if case.startswith("original") else "Literal ⟨EMAIL_1⟩"
        reject = case != "literal-in-text"
        before = masker.vault.to_dict()
        error, reply = None, None
        try:
            if api == "responses":
                result = wrapped.create_response(
                    model=MODEL, input=text, **({"instructions": later} if reject else {})
                )
                reply = result.output[0].content[0].text
            else:
                messages = [{"role": "user", "content": text}]
                kwargs = {}
                if api == "anthropic":
                    kwargs["max_tokens"] = 64
                    if reject:
                        kwargs["system"] = later
                elif reject:
                    messages.append({"role": "user", "content": later})
                result = wrapped.create(model=MODEL, messages=messages, **kwargs)
                reply = (
                    result.content[0].text
                    if api == "anthropic"
                    else result.choices[0].message.content
                )
        except VaultError as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            raw_client.close()
        checks = {
            "expectedRejection": (error is not None) == reject,
            "transportBoundary": len(wire.requests) == (0 if reject else 1),
            "roundTrip": reply is None if reject else reply == text,
            "vaultRollback": masker.vault.to_dict() == before if reject else len(masker.vault) == 1,
        }
        results.append(
            {
                "case": f"{api}-{case}",
                "source": text,
                "laterField": later if reject else None,
                "requests": wire.requests,
                "restoredReply": reply,
                "error": error,
                "vault": masker.vault.to_dict(),
                "checks": checks,
                "agrees": all(checks.values()),
            }
        )

print(
    json.dumps(
        {
            "label": args.label,
            "python": platform.python_version(),
            "sdkVersions": {
                name: importlib.metadata.version(name) for name in ["openai", "anthropic"]
            },
            "scope": "Real SDK serialization and parsing over mock HTTP echo transports; no live provider/model call.",
            "cases": len(results),
            "disagreements": sum(not row["agrees"] for row in results),
            "results": results,
        },
        indent=2,
        ensure_ascii=False,
    )
)
