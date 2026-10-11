"""Inspect serialized tool history at the real SDK's HTTP boundary."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

import pytest

from tests.sdk_wire import MODEL, Wire, chat_completion, response_object
from veil import Masker, VaultError
from veil.integrations.openai import AsyncOpenAIVeil, OpenAIVeil

openai = pytest.importorskip("openai")


def history(api: str, arguments: str) -> dict[str, Any]:
    if api == "chat":
        return {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": "call_1",
                            "function": {"name": "send_email", "arguments": arguments},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "Done"},
            ]
        }
    return {
        "input": [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "send_email",
                "arguments": arguments,
            },
            {"type": "function_call_output", "call_id": "call_1", "output": "Done"},
        ]
    }


def sent_arguments(body: dict[str, Any], api: str) -> str:
    if api == "chat":
        return str(body["messages"][0]["tool_calls"][0]["function"]["arguments"])
    return str(body["input"][0]["arguments"])


@pytest.mark.parametrize("api", ["chat", "responses"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("method", ["create", "create_stream", "stream"])
@pytest.mark.parametrize("case", ["escaped", "invalid", "sensitive_key", "cross_field_collision"])
def test_masking_or_rejection_happens_before_every_sdk_entrypoint(
    api: str, asynchronous: bool, method: str, case: str
) -> None:
    arguments = {
        "escaped": r'{"to":"alice\u0040example.org","literal":"\u27E8EMAIL_1\u27E9"}',
        "invalid": r'{"to":"alice\u0040example.org"',
        "sensitive_key": r'{"alice\u0040example.org":"yes"}',
        "cross_field_collision": r'{"literal":"\u27E8EMAIL_1\u27E9"}',
    }[case]
    kwargs = history(api, arguments)
    if case == "cross_field_collision":
        if api == "chat":
            kwargs["messages"].insert(0, {"role": "user", "content": "alice@example.org"})
        else:
            kwargs["input"].insert(0, {"role": "user", "content": "alice@example.org"})
    original = copy.deepcopy(kwargs)
    wire = Wire(
        openai,
        lambda body: (
            []
            if method != "create"
            else (
                chat_completion("Done") if api == "chat" else response_object("completed", "Done")
            )
        ),
    )
    masker = Masker()
    before = masker.vault.to_json()
    name = "stream" if method == "stream" else "create"
    if api == "responses":
        name += "_response"
    if method == "create_stream":
        kwargs["stream"] = True

    async def run_async() -> None:
        client = openai.AsyncOpenAI(api_key="test", http_client=wire.async_client(), max_retries=0)
        try:
            wrapped = AsyncOpenAIVeil(client, masker=masker)
            if case != "escaped":
                with pytest.raises(VaultError):
                    await getattr(wrapped, name)(model=MODEL, **kwargs)
            else:
                result = await getattr(wrapped, name)(model=MODEL, **kwargs)
                if method != "create":
                    async for _ in result:
                        pass
        finally:
            await client.close()

    if asynchronous:
        asyncio.run(run_async())
    else:
        with openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0) as client:
            wrapped = OpenAIVeil(client, masker=masker)
            if case != "escaped":
                with pytest.raises(VaultError):
                    getattr(wrapped, name)(model=MODEL, **kwargs)
            else:
                result = getattr(wrapped, name)(model=MODEL, **kwargs)
                if method != "create":
                    list(result)
    assert {k: v for k, v in kwargs.items() if k != "stream"} == original
    if case == "escaped":
        assert len(wire.requests) == 1
        assert json.loads(sent_arguments(wire.requests[0], api)) == {
            "to": "⟨EMAIL_2⟩",
            "literal": "⟨EMAIL_1⟩",
        }
    else:
        assert wire.requests == []
        assert masker.vault.to_json() == before


@pytest.mark.parametrize("api", ["chat", "responses"])
def test_echo_restores_values_and_history_replays_exact_provider_arguments(api: str) -> None:
    raw = r'{ "to":"alice\u0040example.org", "count":1.00e+2 }'
    wire = Wire(
        openai,
        lambda body: (
            chat_completion(None, sent_arguments(body, api))
            if api == "chat"
            else response_object("completed", arguments=sent_arguments(body, api))
        ),
    )
    with openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0) as client:
        wrapped = OpenAIVeil(client)
        if api == "chat":
            result = wrapped.create(model=MODEL, **history(api, raw))
            message = result.choices[0].message
            assert json.loads(message.tool_calls[0].function.arguments) == json.loads(raw)
            wrapped.create(model=MODEL, messages=[message])
        else:
            result = wrapped.create_response(model=MODEL, **history(api, raw))
            assert json.loads(result.output[0].arguments) == json.loads(raw)
            wrapped.create_response(model=MODEL, input=result.output)
    assert sent_arguments(wire.requests[0], api) == sent_arguments(wire.requests[1], api)
