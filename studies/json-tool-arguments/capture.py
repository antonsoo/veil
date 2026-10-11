"""Retain real SDK serialization of synthetic tool history over local mock HTTP.

Uses tests/sdk_wire.py only for wire response envelopes, never a live model.
Omit --source to exercise the installed package instead of a source checkout.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
from contextlib import suppress
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
from veil import Masker, VaultError  # noqa: E402
from veil.backends import KnownEntitiesBackend  # noqa: E402
from veil.integrations.openai import OpenAIVeil  # noqa: E402

CASES = {
    "escaped-address": (r'{"to":"alice\u0040example.org"}', False),
    "fully-escaped-address": (
        '{"to":"' + "".join(f"\\u{ord(c):04x}" for c in "alice@example.org") + '"}',
        False,
    ),
    "nested-known-person": (
        r'{"people":[{"name":"Zo\u00eb Example","email":"alice\u0040example.org"}],"enabled":true}',
        False,
    ),
    "literal-placeholder": (
        r'{"to":"alice\u0040example.org","example":"\u27E8EMAIL_1\u27E9"}',
        False,
    ),
    "literal-backslash": (
        r'{"example":"alice\\u0040example.org","emoji":"\ud83d\ude00","n":1.20e+03}',
        False,
    ),
    "truncated-arguments": (r'{"to":"alice\u0040example.org"', True),
    "non-json-number": (r'{"to":"alice\u0040example.org","n":NaN}', True),
    "sensitive-field-name": (r'{"alice\u0040example.org":"yes"}', True),
}


def arguments_in(body, api):
    return (
        body["messages"][0]["tool_calls"][0]["function"]["arguments"]
        if api == "chat"
        else body["input"][0]["arguments"]
    )


def reject_non_json_constant(value):
    raise ValueError("Non-JSON numeric constant")


results = []
for api in ["chat", "responses"]:
    for case, (source, reject) in CASES.items():

        def echo(body, api=api):
            arguments = arguments_in(body, api)
            return (
                chat_completion(None, arguments)
                if api == "chat"
                else response_object("completed", arguments=arguments)
            )

        wire = Wire(openai, echo)
        masker = Masker(name_backends=[KnownEntitiesBackend(persons=["Zoë Example"])])
        before = masker.vault.to_dict()
        error, restored, decoded = None, None, None
        with openai.OpenAI(
            api_key="synthetic-local-test", http_client=wire.client(), max_retries=0
        ) as client:
            wrapped = OpenAIVeil(client, masker=masker)
            try:
                if api == "chat":
                    result = wrapped.create(
                        model=MODEL,
                        messages=[
                            {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "type": "function",
                                        "id": "call_1",
                                        "function": {"name": "send_email", "arguments": source},
                                    }
                                ],
                            },
                            {"role": "tool", "tool_call_id": "call_1", "content": "Done"},
                        ],
                    )
                    restored = result.choices[0].message.tool_calls[0].function.arguments
                else:
                    result = wrapped.create_response(
                        model=MODEL,
                        input=[
                            {
                                "type": "function_call",
                                "call_id": "call_1",
                                "name": "send_email",
                                "arguments": source,
                            },
                            {"type": "function_call_output", "call_id": "call_1", "output": "Done"},
                        ],
                    )
                    restored = result.output[0].arguments
            except VaultError as exc:
                error = {"type": type(exc).__name__, "message": str(exc)}
        if wire.requests:
            with suppress(ValueError):
                decoded = json.loads(
                    arguments_in(wire.requests[0], api), parse_constant=reject_non_json_constant
                )
        checks = {
            "expected_rejection": (error is not None) == reject,
            "transport_boundary": len(wire.requests) == (0 if reject else 1),
            "decoded_contact_absent": not wire.requests
            if reject
            else (
                decoded is not None
                and all(
                    value not in json.dumps(decoded, ensure_ascii=False)
                    for value in ["alice@example.org", "Zoë Example"]
                )
            ),
            "round_trip": restored is None
            if reject
            else json.loads(restored) == json.loads(source),
            "vault_rollback": masker.vault.to_dict() == before if reject else True,
        }
        results.append(
            {
                "api": api,
                "case": case,
                "source_arguments": source,
                "requests": wire.requests,
                "decoded_sent_arguments": decoded,
                "restored_arguments": restored,
                "error": error,
                "vault": masker.vault.to_dict(),
                "checks": checks,
                "agrees": all(checks.values()),
            }
        )

receipt = {
    "label": args.label,
    "python": platform.python_version(),
    "openai_sdk": importlib.metadata.version("openai"),
    "scope": "Synthetic contacts; real SDK serialization with local mock HTTP. No provider calls or real credentials.",
    "cases": len(results),
    "disagreements": sum(not row["agrees"] for row in results),
    "results": results,
}
print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
if args.check and receipt["disagreements"]:
    raise SystemExit(1)
