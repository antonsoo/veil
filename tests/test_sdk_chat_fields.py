"""Capture actual SDK request bodies for text fields outside ordinary content."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

import pytest

from tests.sdk_wire import MODEL, Wire, chat_completion

openai = pytest.importorskip("openai")

from veil.integrations._common import get_field, model_copy_with  # noqa: E402
from veil.integrations.openai import AsyncOpenAIVeil, OpenAIVeil  # noqa: E402
from veil.vault import VaultError  # noqa: E402

PII = "alice@example.com"
OTHER = "bob@example.org"
FIELDS = ["refusal", "refusal-part", "legacy", "custom"]
OUTPUT_FIELDS = ["refusal", "legacy", "custom"]


def message(kind: str, text: str) -> dict[str, Any]:
    result: dict[str, Any] = {"role": "assistant", "content": None}
    if kind == "refusal":
        result["refusal"] = text
    elif kind == "refusal-part":
        result["content"] = [{"type": "refusal", "refusal": text}]
    elif kind == "legacy":
        result["function_call"] = {"name": "contact", "arguments": text}
    else:
        result["tool_calls"] = [
            {"id": "call_1", "type": "custom", "custom": {"name": "contact", "input": text}}
        ]
    return result


def value(item: Any, kind: str) -> str:
    if kind == "refusal":
        return str(get_field(item, "refusal"))
    if kind == "refusal-part":
        return str(get_field(get_field(item, "content")[0], "refusal"))
    if kind == "legacy":
        return str(get_field(get_field(item, "function_call"), "arguments"))
    return str(get_field(get_field(get_field(item, "tool_calls")[0], "custom"), "input"))


def text_for(kind: str, address: str) -> str:
    if kind == "legacy":
        # Arbitrary-precision integers, duplicate members and whitespace must
        # survive the shared JSON-argument masking path byte-for-byte.
        return '{\n "to": "' + address + '", "n": 9007199254740993, "x": 1, "x": 2\n}'
    return f"Cannot contact {address}."


def reply(kind: str, text: str) -> dict[str, Any]:
    result = chat_completion(None)
    result["choices"][0]["message"] = message(kind, text)
    return result


@pytest.mark.parametrize("kind", FIELDS)
@pytest.mark.parametrize("asynchronous", [False, True])
def test_raw_history_is_masked_before_the_real_sdk_transport(kind: str, asynchronous: bool) -> None:
    wire = Wire(openai, lambda body: chat_completion("ok"))
    original = message(kind, text_for(kind, PII))
    before = deepcopy(original)

    async def run_async() -> None:
        async with openai.AsyncOpenAI(
            api_key="test", http_client=wire.async_client(), max_retries=0
        ) as sdk:
            wrapped = AsyncOpenAIVeil(sdk)
            await wrapped.create(model=MODEL, messages=[original])

    if asynchronous:
        asyncio.run(run_async())
    else:
        with openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
            OpenAIVeil(sdk).create(model=MODEL, messages=[original])
    sent = wire.requests[0]["messages"][0]
    assert PII not in wire.sent()
    assert value(sent, kind) == text_for(kind, "⟨EMAIL_1⟩")
    assert original == before


@pytest.mark.parametrize("kind", OUTPUT_FIELDS)
@pytest.mark.parametrize("asynchronous", [False, True])
def test_complete_reply_restores_and_unchanged_sdk_history_replays_exactly(
    kind: str,
    asynchronous: bool,
) -> None:
    provider_text = text_for(kind, "⟨email_1⟩")
    provider = reply(kind, provider_text)
    before = deepcopy(provider)
    wire = Wire(openai, lambda body: provider)
    prompt = [{"role": "user", "content": f"Contact {PII}"}]

    def check(restored: Any) -> None:
        assert value(restored, kind) == text_for(kind, PII)

    async def run_async() -> None:
        async with openai.AsyncOpenAI(
            api_key="test", http_client=wire.async_client(), max_retries=0
        ) as sdk:
            wrapped = AsyncOpenAIVeil(sdk)
            restored = (await wrapped.create(model=MODEL, messages=prompt)).choices[0].message
            check(restored)
            await wrapped.create(model=MODEL, messages=[*prompt, restored])

    if asynchronous:
        asyncio.run(run_async())
    else:
        with openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
            wrapped = OpenAIVeil(sdk)
            restored = wrapped.create(model=MODEL, messages=prompt).choices[0].message
            check(restored)
            wrapped.create(model=MODEL, messages=[*prompt, restored])
    assert value(wire.requests[1]["messages"][1], kind) == provider_text
    assert PII not in wire.sent()
    assert provider == before


@pytest.mark.parametrize("kind", OUTPUT_FIELDS)
def test_edited_sdk_history_is_masked_again(kind: str) -> None:
    wire = Wire(openai, lambda body: reply(kind, text_for(kind, "⟨EMAIL_1⟩")))
    with openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
        wrapped = OpenAIVeil(sdk)
        restored = (
            wrapped.create(model=MODEL, messages=[{"role": "user", "content": f"Contact {PII}"}])
            .choices[0]
            .message
        )
        if kind == "refusal":
            edited = restored.model_copy(update={"refusal": text_for(kind, OTHER)})
        elif kind == "legacy":
            edited = restored.model_copy(
                update={
                    "function_call": model_copy_with(
                        restored.function_call, arguments=text_for(kind, OTHER)
                    )
                }
            )
        else:
            call = restored.tool_calls[0]
            edited = restored.model_copy(
                update={
                    "tool_calls": [
                        model_copy_with(
                            call,
                            custom=model_copy_with(
                                get_field(call, "custom"), input=text_for(kind, OTHER)
                            ),
                        )
                    ]
                }
            )
        wrapped.create(model=MODEL, messages=[edited])
    assert PII not in wire.sent() and OTHER not in wire.sent()
    assert value(wire.requests[-1]["messages"][0], kind) == text_for(kind, "⟨EMAIL_2⟩")


@pytest.mark.parametrize("kind", FIELDS)
def test_literal_surrogate_in_newly_covered_field_rejects_before_transport(kind: str) -> None:
    wire = Wire(openai, lambda body: chat_completion("ok"))
    with openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
        wrapped = OpenAIVeil(sdk)
        with pytest.raises(VaultError):
            wrapped.create(
                model=MODEL,
                messages=[
                    {"role": "user", "content": f"Contact {PII}"},
                    message(kind, text_for(kind, "⟨EMAIL_1⟩")),
                ],
            )
        assert len(wrapped.masker.vault) == 0
    assert wire.requests == []


@pytest.mark.parametrize("kind", OUTPUT_FIELDS)
def test_raw_sdk_message_objects_are_masked_without_mutation(kind: str) -> None:
    wire = Wire(openai, lambda body: reply(kind, text_for(kind, PII)))
    with openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
        raw = (
            sdk.chat.completions.create(
                model=MODEL, messages=[{"role": "user", "content": "Return the local fixture"}]
            )
            .choices[0]
            .message
        )
        original = raw.model_dump()
        OpenAIVeil(sdk).create(model=MODEL, messages=[raw])
    assert PII not in wire.sent()
    assert raw.model_dump() == original
