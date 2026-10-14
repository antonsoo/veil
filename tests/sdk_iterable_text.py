"""Synthetic array-shape controls and actual SDK transport capture."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from tests.sdk_wire import (
    MODEL,
    Wire,
    chat_chunk,
    chat_completion,
    choice_delta,
    response_object,
    responses_stream,
)

PII = "alice@example.org"
KINDS = (
    "chat-text",
    "chat-refusal",
    "response-content",
    "response-tool-output",
    "response-summary",
    "response-input",
)
SHAPES = ("list", "tuple", "generator")
MODES = ("complete", "create-stream", "stream")


def capture(
    kind: str, shape: str, asynchronous: bool, mode: str, *, collision: bool = False
) -> dict[str, Any]:
    """Build each one-shot input afresh and capture requests after SDK serialization."""
    import openai

    from veil import Masker
    from veil.integrations.openai import AsyncOpenAIVeil, OpenAIVeil

    arrays: list[list[Any]] = []

    def array(items: list[Any]) -> Any:
        arrays.append(items)
        if shape == "tuple":
            return tuple(items)
        if shape == "generator":
            return (item for item in items)
        return items

    text = "⟨EMAIL_1⟩" if collision else f"Contact {PII}."
    if kind == "chat-text":
        content = array(
            [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": "https://example.invalid/opaque.png"}},
            ]
        )
        messages = [{"role": "user", "content": content}]
    elif kind == "chat-refusal":
        messages = [{"role": "assistant", "content": array([{"type": "refusal", "refusal": text}])}]
    elif kind == "response-content":
        messages = [{"role": "user", "content": array([{"type": "input_text", "text": text}])}]
    elif kind == "response-tool-output":
        messages = [
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": array([{"type": "input_text", "text": text}]),
            }
        ]
    elif kind == "response-summary":
        messages = [
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": array([{"type": "summary_text", "text": text}]),
                "encrypted_content": "opaque-signature",
            }
        ]
    else:
        messages = [{"role": "user", "content": text}]
    if collision:
        messages.insert(0, {"role": "user", "content": f"Contact {PII}."})
    items = array(messages) if kind == "response-input" else messages
    # arrays may contain a generator nested in a message. Retain only its
    # original plain blocks for mutation checks, not a copy of the iterator.
    source_blocks = [deepcopy(a) for a in arrays if all("role" not in x for x in a)]
    plain_arrays = [a for a in arrays if all("role" not in x for x in a)]
    source_messages = (
        deepcopy(messages) if shape != "generator" or kind == "response-input" else None
    )
    masker = Masker()

    def reply(body: dict[str, Any]) -> Any:
        if kind.startswith("chat"):
            if body.get("stream"):
                return [
                    chat_chunk(choice_delta(content="ok")),
                    chat_chunk(choice_delta(finish="stop")),
                    "[DONE]",
                ]
            return chat_completion("ok")
        return (
            responses_stream(["ok"], [])
            if body.get("stream")
            else response_object("completed", "ok")
        )

    wire = Wire(openai, reply)
    failure = None

    def kwargs() -> dict[str, Any]:
        return {"model": MODEL, "messages" if kind.startswith("chat") else "input": items}

    async def run_async() -> None:
        async with openai.AsyncOpenAI(
            api_key="unused", http_client=wire.async_client(), max_retries=0
        ) as sdk:
            wrapped = AsyncOpenAIVeil(sdk, masker=masker)
            create = wrapped.create if kind.startswith("chat") else wrapped.create_response
            stream = wrapped.stream if kind.startswith("chat") else wrapped.stream_response
            if mode == "complete":
                await create(**kwargs())
            else:
                output = (
                    await stream(**kwargs())
                    if mode == "stream"
                    else await create(**kwargs(), stream=True)
                )
                async with output:
                    async for _ in output:
                        pass

    try:
        if asynchronous:
            asyncio.run(run_async())
        else:
            with openai.OpenAI(api_key="unused", http_client=wire.client(), max_retries=0) as sdk:
                wrapped = OpenAIVeil(sdk, masker=masker)
                create = wrapped.create if kind.startswith("chat") else wrapped.create_response
                stream = wrapped.stream if kind.startswith("chat") else wrapped.stream_response
                if mode == "complete":
                    create(**kwargs())
                else:
                    output = (
                        stream(**kwargs()) if mode == "stream" else create(**kwargs(), stream=True)
                    )
                    with output:
                        list(output)
    except Exception as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)}
    assert plain_arrays == source_blocks
    if source_messages is not None:
        assert messages == source_messages
    return {
        "kind": kind,
        "shape": shape,
        "async": asynchronous,
        "mode": mode,
        "collision": collision,
        "requests": wire.requests,
        "failure": failure,
        "vaultEntriesAfter": len(masker.vault),
        "recognizedRawContactSent": PII in wire.sent(),
        "originalBlocksUnchanged": True,
        "oneShotIterator": shape == "generator",
    }
