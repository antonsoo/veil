"""Actual SDK tool-input masking and JSON-safe restoration with synthetic contacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import anthropic
import openai

from veil.detectors import email as email_module
from veil.integrations.anthropic import AnthropicVeil
from veil.integrations.openai import OpenAIVeil

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from tests.sdk_wire import (  # noqa: E402
    MODEL,
    Wire,
    anthropic_message,
    chat_completion,
    response_object,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    ids = {
        "bang-interior",
        "slash-interior",
        "quoted-space",
        "quoted-mailbox-inside",
        "quoted-escape",
        "unicode-local",
        "unicode-domain",
    }
    cases = [c for c in json.loads((HERE / "cases.json").read_text())["cases"] if c["id"] in ids]
    rows = []
    for case in cases:
        address = case["address"]
        # Keep number spelling and duplicate keys in the string APIs, beyond
        # merely testing whether their decoded dictionaries happen to agree.
        arguments = (
            '{\n "to": '
            + json.dumps(address, ensure_ascii=False)
            + ', "n": 9007199254740993, "x": 1, "x": 2\n}'
        )
        expected = arguments.replace(json.dumps(address, ensure_ascii=False), '"⟨EMAIL_1⟩"')
        for api in ("chat", "responses", "anthropic"):
            sdk = anthropic if api == "anthropic" else openai

            def echo(body: dict[str, Any], api: str = api) -> dict[str, Any]:
                if api == "responses":
                    return response_object("completed", arguments=body["input"][0]["arguments"])
                if api == "chat":
                    return chat_completion(
                        None, body["messages"][0]["tool_calls"][0]["function"]["arguments"]
                    )
                tool = body["messages"][0]["content"][0]
                return anthropic_message([tool], stop_reason="tool_use")

            wire = Wire(sdk, echo)
            client_type = sdk.Anthropic if api == "anthropic" else sdk.OpenAI
            wrapper_type = AnthropicVeil if api == "anthropic" else OpenAIVeil
            with client_type(api_key="test", http_client=wire.client(), max_retries=0) as client:
                wrapped = wrapper_type(client)
                if api == "responses":
                    reply = wrapped.create_response(
                        model=MODEL,
                        input=[
                            {
                                "type": "function_call",
                                "call_id": "call_1",
                                "name": "contact",
                                "arguments": arguments,
                            }
                        ],
                    )
                    outgoing = wire.requests[0]["input"][0]["arguments"]
                    returned = reply.output[0].arguments
                elif api == "chat":
                    reply = wrapped.create(
                        model=MODEL,
                        messages=[
                            {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "contact",
                                            "arguments": arguments,
                                        },
                                    }
                                ],
                            }
                        ],
                    )
                    outgoing = wire.requests[0]["messages"][0]["tool_calls"][0]["function"][
                        "arguments"
                    ]
                    returned = reply.choices[0].message.tool_calls[0].function.arguments
                else:
                    tool = {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "contact",
                        "input": json.loads(arguments),
                    }
                    reply = wrapped.create(
                        model=MODEL,
                        max_tokens=64,
                        messages=[{"role": "assistant", "content": [tool]}],
                    )
                    outgoing = wire.requests[0]["messages"][0]["content"][0]["input"]
                    returned = reply.content[0].input
                assert (
                    returned == json.loads(arguments)
                    if api == "anthropic"
                    else returned == arguments
                )
                correct = outgoing == (json.loads(expected) if api == "anthropic" else expected)
                if args.require_fixed:
                    assert correct, (case, api, outgoing)
                rows.append(
                    {
                        "id": case["id"],
                        "api": api,
                        "request": wire.requests[0],
                        "completeMask": correct,
                        "exactRestore": True,
                    }
                )
    result = {
        "versions": {p: version(p) for p in ("veil-pii", "openai", "anthropic")},
        "emailSourceSha256": hashlib.sha256(Path(email_module.__file__).read_bytes()).hexdigest(),
        "workflows": rows,
        "completeMasks": sum(r["completeMask"] for r in rows),
        "transport": "Actual SDKs over mocked HTTP; synthetic inputs and replies, no provider contact.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"{result['completeMasks']}/{len(rows)} complete tool inputs; all restore exactly")


if __name__ == "__main__":
    main()
