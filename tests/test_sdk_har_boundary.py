"""Ambiguous HAR cookie routing must refuse before SDK HTTP serialization."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.sdk_wire import Wire, anthropic_message, chat_completion, response_object

openai = pytest.importorskip("openai")
anthropic = pytest.importorskip("anthropic")

from veil import Masker, VaultError  # noqa: E402
from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil  # noqa: E402
from veil.integrations.openai import AsyncOpenAIVeil, OpenAIVeil  # noqa: E402

AMBIGUOUS = '{"log":{"version":"1.2","entries":[{"request":{"headers":[{"name":"Cookie","name":"X-Public","value":"sid=short"}]}}]}}'
TYPED_BAD = {
    "log": {
        "version": "1.2",
        "entries": [{"request": {"headers": [{"name": "Cookie", "value": 17}]}}],
    }
}


@pytest.mark.parametrize("api", ["chat", "responses", "anthropic"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_har_rejection_leaves_no_request_and_rolls_back(api: str, asynchronous: bool) -> None:
    sdk = anthropic if api == "anthropic" else openai
    wire = Wire(
        sdk,
        lambda _body: (
            anthropic_message([])
            if api == "anthropic"
            else response_object("completed")
            if api == "responses"
            else chat_completion("unused")
        ),
    )
    masker = Masker()
    masker.mask("Cookie: sid=existing")
    before = masker.vault.to_json()
    if api == "anthropic":
        kwargs = {
            "model": "test",
            "max_tokens": 32,
            "messages": [
                {"role": "user", "content": "alice@example.org"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "call_1", "name": "inspect", "input": TYPED_BAD}
                    ],
                },
            ],
        }
    elif api == "responses":
        kwargs = {
            "model": "test",
            "input": [
                {"role": "user", "content": "alice@example.org"},
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "inspect",
                    "arguments": AMBIGUOUS,
                },
            ],
        }
    else:
        kwargs = {
            "model": "test",
            "messages": [
                {"role": "user", "content": "alice@example.org"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "inspect", "arguments": AMBIGUOUS},
                        }
                    ],
                },
            ],
        }
    original = json.dumps(kwargs, sort_keys=True)

    async def invoke_async() -> None:
        client_type = sdk.AsyncAnthropic if api == "anthropic" else sdk.AsyncOpenAI
        wrapper = AsyncAnthropicVeil if api == "anthropic" else AsyncOpenAIVeil
        async with client_type(
            api_key="test", http_client=wire.async_client(), max_retries=0
        ) as client:
            wrapped = wrapper(client, masker=masker)
            call = wrapped.create_response if api == "responses" else wrapped.create
            await call(**kwargs)

    with pytest.raises(VaultError, match="HAR"):
        if asynchronous:
            asyncio.run(invoke_async())
        else:
            client_type = sdk.Anthropic if api == "anthropic" else sdk.OpenAI
            wrapper = AnthropicVeil if api == "anthropic" else OpenAIVeil
            with client_type(api_key="test", http_client=wire.client(), max_retries=0) as client:
                wrapped = wrapper(client, masker=masker)
                call = wrapped.create_response if api == "responses" else wrapped.create
                call(**kwargs)
    assert wire.requests == []
    assert masker.vault.to_json() == before
    assert json.dumps(kwargs, sort_keys=True) == original
