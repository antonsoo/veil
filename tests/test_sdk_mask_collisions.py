"""Real SDK transports see no request when raw-text masking is ambiguous."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tests.sdk_wire import MODEL, Wire, anthropic_message, chat_completion, response_object
from veil import VaultError
from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil
from veil.integrations.openai import AsyncOpenAIVeil, OpenAIVeil
from veil.integrations.openai import mask_messages as mask_chat_messages

openai = pytest.importorskip("openai")
anthropic = pytest.importorskip("anthropic")


def test_failed_preparation_preserves_attribute_objects_for_retry() -> None:
    from veil import Masker

    first = SimpleNamespace(role="user", content="alice@example.org")
    second = SimpleNamespace(role="user", content="Literal ⟨EMAIL_1⟩")
    masker = Masker()
    with pytest.raises(VaultError):
        mask_chat_messages([first, second], masker)
    assert first.content == "alice@example.org"
    assert second.content == "Literal ⟨EMAIL_1⟩"
    assert len(masker.vault) == 0


def client_for(api: str, asynchronous: bool) -> tuple[Any, Wire]:
    sdk = anthropic if api == "anthropic" else openai
    wire = Wire(sdk, lambda body: {})
    if asynchronous:
        client = sdk.AsyncAnthropic if api == "anthropic" else sdk.AsyncOpenAI
        wrapper = AsyncAnthropicVeil if api == "anthropic" else AsyncOpenAIVeil
        return wrapper(client(api_key="test", http_client=wire.async_client(), max_retries=0)), wire
    client = sdk.Anthropic if api == "anthropic" else sdk.OpenAI
    wrapper = AnthropicVeil if api == "anthropic" else OpenAIVeil
    return wrapper(client(api_key="test", http_client=wire.client(), max_retries=0)), wire


@pytest.mark.parametrize("api", ["anthropic", "chat", "responses"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("method", ["create", "create_stream", "stream"])
def test_all_entrypoints_reject_cross_field_collision_before_transport(
    api: str, asynchronous: bool, method: str
) -> None:
    wrapped, wire = client_for(api, asynchronous)
    # The first text allocates a token that the later field contains literally.
    kwargs: dict[str, Any] = {"model": MODEL}
    if api == "responses":
        kwargs.update(input="alice@example.org", instructions="Literal ⟨EMAIL_1⟩")
    elif api == "anthropic":
        kwargs.update(
            messages=[{"role": "user", "content": "alice@example.org"}],
            system="Literal ⟨EMAIL_1⟩",
            max_tokens=64,
        )
    else:
        kwargs.update(
            messages=[
                {"role": "user", "content": "alice@example.org"},
                {"role": "user", "content": "Literal ⟨EMAIL_1⟩"},
            ]
        )
    name = "stream" if method == "stream" else "create"
    if api == "responses":
        name += "_response"
    if method == "create_stream":
        kwargs["stream"] = True
    before = wrapped.masker.vault.to_json()
    if asynchronous:

        async def run() -> None:
            try:
                with pytest.raises(VaultError, match="conflicts"):
                    await getattr(wrapped, name)(**kwargs)
            finally:
                await wrapped.client.close()

        asyncio.run(run())
    else:
        try:
            with pytest.raises(VaultError, match="conflicts"):
                getattr(wrapped, name)(**kwargs)
        finally:
            wrapped.client.close()
    assert wire.requests == []
    assert wrapped.masker.vault.to_json() == before


@pytest.mark.parametrize("api", ["anthropic", "chat", "responses"])
def test_literal_example_and_contact_round_trip_through_sdk_echo(api: str) -> None:
    wrapped, wire = client_for(api, False)
    source = "Contact alice@example.org; example ⟨email_1⟩."
    if api == "anthropic":
        wire.reply = lambda body: anthropic_message(
            [
                {"type": "text", "text": body["messages"][0]["content"]},
            ]
        )
        reply = (
            wrapped.create(
                model=MODEL, max_tokens=64, messages=[{"role": "user", "content": source}]
            )
            .content[0]
            .text
        )
    elif api == "responses":
        wire.reply = lambda body: response_object("completed", body["input"])
        reply = wrapped.create_response(model=MODEL, input=source).output[0].content[0].text
    else:
        wire.reply = lambda body: chat_completion(body["messages"][0]["content"])
        reply = (
            wrapped.create(model=MODEL, messages=[{"role": "user", "content": source}])
            .choices[0]
            .message.content
        )
    assert reply == source
    assert len(wire.requests) == 1
    assert "alice@example.org" not in wire.sent()
    assert "⟨EMAIL_2⟩" in wire.sent() and "⟨email_1⟩" in wire.sent()
    wrapped.client.close()
