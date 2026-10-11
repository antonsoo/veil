"""Capture complete SDK tool replies without real credentials or provider calls."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--label", default="installed")
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

import openai  # noqa: E402

from tests.sdk_wire import MODEL, Wire, chat_completion, response_object  # noqa: E402
from veil import Masker  # noqa: E402
from veil.integrations.openai import OpenAIVeil  # noqa: E402

CASES = {
    "decimal-precision": '{"to":"⟨EMAIL_1⟩","amount":0.12345678901234567890}',
    "large-exponent": '{"to":"⟨EMAIL_1⟩","n":1e309}',
    "duplicate-members": '{"to":"⟨EMAIL_1⟩","n":1,"n":2}',
    "numeric-spelling": ' {"to":"⟨EMAIL_1⟩","n":-0.00E-03,"key":"\\u0061"}\n',
    "escaped-surrogate": '{"to":"\\u27E8EMAIL_1\\u27E9","n":1.00e+2}',
    "tolerant-surrogate": '{"to":"⟨email_1⟩","n":1.00e+2}',
    "no-surrogate": '{"n":1e309,"n":2,"text":"\\u0061"}',
    "truncated": '{"to":"⟨EMAIL_1⟩","n":',
}
results = []
for api in ["chat", "responses"]:
    for case, raw in CASES.items():
        masker = Masker()
        masker.mask("alice@example.org")
        original_response = (
            chat_completion(None, raw)
            if api == "chat"
            else response_object("completed", arguments=raw)
        )
        wire = Wire(openai, lambda body, reply=original_response: reply)
        with openai.OpenAI(
            api_key="synthetic-local-test", http_client=wire.client(), max_retries=0
        ) as client:
            wrapped = OpenAIVeil(client, masker=masker)
            if api == "chat":
                response = wrapped.create(
                    model=MODEL, messages=[{"role": "user", "content": "Continue"}]
                )
                restored = response.choices[0].message.tool_calls[0].function.arguments
                wrapped.create(model=MODEL, messages=[response.choices[0].message])
                replayed = wire.requests[1]["messages"][0]["tool_calls"][0]["function"]["arguments"]
            else:
                response = wrapped.create_response(model=MODEL, input="Continue")
                restored = response.output[0].arguments
                wrapped.create_response(model=MODEL, input=response.output)
                replayed = wire.requests[1]["input"][0]["arguments"]
        expected = (
            raw.replace("⟨EMAIL_1⟩", "alice@example.org")
            .replace("⟨email_1⟩", "alice@example.org")
            .replace(r"\u27E8EMAIL_1\u27E9", "alice@example.org")
        )
        checks = {
            "restoration_preserves_other_tokens": restored == expected,
            "history_replays_original_arguments": replayed == raw,
        }
        results.append(
            {
                "api": api,
                "case": case,
                "provider_response": original_response,
                "restored_arguments": restored,
                "expected_arguments": expected,
                "replayed_arguments": replayed,
                "checks": checks,
                "agrees": all(checks.values()),
            }
        )
receipt = {
    "label": args.label,
    "python": platform.python_version(),
    "openai_sdk": importlib.metadata.version("openai"),
    "scope": "Synthetic local SDK captures. No provider calls. Only restored string tokens may change.",
    "cases": len(results),
    "disagreements": sum(not row["agrees"] for row in results),
    "results": results,
}
print(json.dumps(receipt, ensure_ascii=False, indent=2))
if args.check and receipt["disagreements"]:
    raise SystemExit(1)
