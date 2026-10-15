"""Capture the auth-key context that per-string JSON masking previously lost."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.sdk_wire import (  # noqa: E402
    MODEL,
    Wire,
    anthropic_message,
    anthropic_stream,
    chat_chunk,
    chat_completion,
    choice_delta,
    response_object,
    responses_stream,
)

RAW = r'{ "headers":{"Authoriz\u0061tion":"Basic dXNlcjpwYXNz", "Proxy-Authorization":"Bearer ab.c_d-ef~g+/=="}, "count":9007199254740993, "count":1.2300e+40, "ordinary":"Bearer xyz" }'
EXPECTED = RAW.replace("dXNlcjpwYXNz", "\u27e8SECRET_1\u27e9").replace(
    "ab.c_d-ef~g+/==", "\u27e8SECRET_2\u27e9"
)


def sdk_tool_capture(api: str, asynchronous: bool, streaming: bool) -> dict[str, Any]:
    import anthropic
    import openai

    from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil
    from veil.integrations.openai import AsyncOpenAIVeil, OpenAIVeil

    sdk = anthropic if api == "anthropic" else openai

    def arguments(body: dict[str, Any]) -> str:
        if api == "anthropic":
            return json.dumps(body["messages"][1]["content"][0]["input"], ensure_ascii=False)
        if api == "chat":
            return str(body["messages"][0]["tool_calls"][0]["function"]["arguments"])
        return str(body["input"][0]["arguments"])

    def echo(body: dict[str, Any]) -> Any:
        text = arguments(body)
        if streaming:
            if api == "responses":
                return responses_stream(list(text), [])
            if api == "anthropic":
                return anthropic_stream([("text", list(text))])
            return [
                *[chat_chunk(choice_delta(content=c)) for c in text],
                chat_chunk(choice_delta(finish="stop")),
                "[DONE]",
            ]
        if api == "responses":
            return response_object("completed", text)
        if api == "anthropic":
            return anthropic_message([{"type": "text", "text": text}])
        return chat_completion(text)

    wire = Wire(sdk, echo)
    kwargs: dict[str, Any] = {"model": MODEL}
    if api == "anthropic":
        kwargs.update(
            max_tokens=64,
            messages=[
                {"role": "user", "content": "Review request."},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "request",
                            "input": json.loads(RAW),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "call_1", "content": "Done"}
                    ],
                },
            ],
        )
    elif api == "chat":
        kwargs["messages"] = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "type": "function",
                        "id": "call_1",
                        "function": {"name": "request", "arguments": RAW},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "Done"},
        ]
    else:
        kwargs["input"] = [
            {"type": "function_call", "call_id": "call_1", "name": "request", "arguments": RAW},
            {"type": "function_call_output", "call_id": "call_1", "output": "Done"},
        ]
    original = copy.deepcopy(kwargs)
    if streaming:
        kwargs["stream"] = True

    def buffered(reply: Any) -> str:
        if api == "responses":
            return str(reply.output[0].content[0].text)
        if api == "anthropic":
            return str(reply.content[0].text)
        return str(reply.choices[0].message.content)

    def pieces(events: list[Any]) -> str:
        if api == "responses":
            return "".join(e.delta for e in events if e.type == "response.output_text.delta")
        if api == "anthropic":
            return "".join(
                e.delta.text
                for e in events
                if e.type == "content_block_delta" and e.delta.type == "text_delta"
            )
        return "".join(c.delta.content or "" for e in events for c in e.choices)

    async def run_async() -> str:
        client_type = sdk.AsyncAnthropic if api == "anthropic" else sdk.AsyncOpenAI
        wrapper = AsyncAnthropicVeil if api == "anthropic" else AsyncOpenAIVeil
        async with client_type(
            api_key="test", http_client=wire.async_client(), max_retries=0
        ) as client:
            wrapped = wrapper(client)
            call = wrapped.create_response if api == "responses" else wrapped.create
            reply = await call(**kwargs)
            return pieces([event async for event in reply]) if streaming else buffered(reply)

    if asynchronous:
        reply_text = asyncio.run(run_async())
    else:
        client_type = sdk.Anthropic if api == "anthropic" else sdk.OpenAI
        wrapper = AnthropicVeil if api == "anthropic" else OpenAIVeil
        with client_type(api_key="test", http_client=wire.client(), max_retries=0) as client:
            wrapped = wrapper(client)
            call = wrapped.create_response if api == "responses" else wrapped.create
            reply = call(**kwargs)
            reply_text = pieces(list(reply)) if streaming else buffered(reply)
    assert {k: v for k, v in kwargs.items() if k != "stream"} == original
    assert len(wire.requests) == 1
    outgoing = arguments(wire.requests[0])
    assert json.loads(reply_text) == json.loads(RAW)
    if api != "anthropic":
        assert reply_text == RAW
    return {
        "api": api,
        "async": asynchronous,
        "stream": streaming,
        "request": wire.requests[0],
        "outgoingArguments": outgoing,
        "correct": json.loads(outgoing) == json.loads(EXPECTED),
        "unrelatedSyntaxPreserved": api == "anthropic" or outgoing in {RAW, EXPECTED},
        "restoresExactly": True,
        "callerInputUnchanged": True,
    }
