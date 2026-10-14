"""SDK array serialization cannot happen later than inline text masking."""

from __future__ import annotations

import pytest

openai = pytest.importorskip("openai")

from tests.sdk_iterable_text import KINDS, MODES, SHAPES, capture  # noqa: E402
from tests.sdk_wire import MODEL, Wire, response_object  # noqa: E402
from veil import Masker  # noqa: E402
from veil.integrations.openai import AsyncOpenAIVeil, OpenAIVeil  # noqa: E402


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("mode", MODES)
def test_actual_sdk_arrays_are_masked_before_transport(
    kind: str, shape: str, asynchronous: bool, mode: str
) -> None:
    result = capture(kind, shape, asynchronous, mode)
    assert result["failure"] is None
    assert len(result["requests"]) == 1
    assert result["recognizedRawContactSent"] is False
    assert result["vaultEntriesAfter"] == 1
    sent = result["requests"][0]
    if kind == "chat-text":
        assert sent["messages"][0]["content"] == [
            {"type": "text", "text": "Contact ⟨EMAIL_1⟩."},
            {"type": "image_url", "image_url": {"url": "https://example.invalid/opaque.png"}},
        ]
    elif kind == "response-summary":
        assert sent["input"][0]["summary"] == [
            {"type": "summary_text", "text": "Contact ⟨EMAIL_1⟩."}
        ]
        assert sent["input"][0]["encrypted_content"] == "opaque-signature"


@pytest.mark.parametrize("kind", ["chat-text", "response-content", "response-input"])
@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("asynchronous", [False, True])
def test_iterator_literal_collisions_roll_back_before_transport(
    kind: str, shape: str, asynchronous: bool
) -> None:
    result = capture(kind, shape, asynchronous, "complete", collision=True)
    assert result["failure"]["type"] == "VaultError"
    assert "surrogate conflicts" in result["failure"]["message"]
    assert not result["requests"]
    assert result["vaultEntriesAfter"] == 0


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("asynchronous", [False, True])
def test_retained_provider_items_replay_exactly_inside_iterable_inputs(
    shape: str, asynchronous: bool
) -> None:
    import asyncio

    provider = response_object("completed", "Contact ⟨email_1⟩.")
    wire = Wire(openai, lambda body: provider)
    prompt = [{"role": "user", "content": "Contact alice@example.org."}]

    def input_for(items: list) -> object:
        if shape == "tuple":
            return tuple(items)
        if shape == "generator":
            return (item for item in items)
        return items

    async def run_async() -> None:
        async with openai.AsyncOpenAI(
            api_key="unused", http_client=wire.async_client(), max_retries=0
        ) as sdk:
            wrapped = AsyncOpenAIVeil(sdk)
            result = await wrapped.create_response(model=MODEL, input=prompt)
            assert result.output_text == "Contact alice@example.org."
            await wrapped.create_response(model=MODEL, input=input_for([*prompt, *result.output]))

    if asynchronous:
        asyncio.run(run_async())
    else:
        with openai.OpenAI(api_key="unused", http_client=wire.client(), max_retries=0) as sdk:
            wrapped = OpenAIVeil(sdk)
            result = wrapped.create_response(model=MODEL, input=prompt)
            assert result.output_text == "Contact alice@example.org."
            wrapped.create_response(model=MODEL, input=input_for([*prompt, *result.output]))
    assert wire.requests[1]["input"][1] == provider["output"][0]
    assert "alice@example.org" not in wire.sent()


@pytest.mark.parametrize("responses", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_failing_one_shot_iterator_rolls_back_without_rewinding_or_transport(
    responses: bool, asynchronous: bool
) -> None:
    import asyncio

    progress: list[str] = []

    def parts():
        progress.append("yield")
        yield {"type": "input_text" if responses else "text", "text": "Contact alice@example.org."}
        progress.append("fail")
        raise RuntimeError("synthetic iterator failure")

    items = [{"role": "user", "content": parts()}]
    wire = Wire(openai, lambda body: response_object("completed"))
    masker = Masker()
    args = {"model": MODEL, "input" if responses else "messages": items}

    async def run_async() -> None:
        async with openai.AsyncOpenAI(
            api_key="unused", http_client=wire.async_client(), max_retries=0
        ) as sdk:
            wrapped = AsyncOpenAIVeil(sdk, masker=masker)
            call = wrapped.create_response if responses else wrapped.create
            with pytest.raises(RuntimeError, match="synthetic iterator failure"):
                await call(**args)

    if asynchronous:
        asyncio.run(run_async())
    else:
        with openai.OpenAI(api_key="unused", http_client=wire.client(), max_retries=0) as sdk:
            wrapped = OpenAIVeil(sdk, masker=masker)
            call = wrapped.create_response if responses else wrapped.create
            with pytest.raises(RuntimeError, match="synthetic iterator failure"):
                call(**args)
    assert progress == ["yield", "fail"]
    assert not wire.requests and len(masker.vault) == 0
    assert list(items[0]["content"]) == []
