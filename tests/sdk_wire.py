"""The APIs' wire format, for running the real SDKs without a network.

``tests/test_sdk_anthropic.py`` and ``tests/test_sdk_openai.py`` hand each SDK an HTTP
client whose transport answers from here: JSON bodies and server-sent event streams in the
shape the Messages, Chat Completions and Responses APIs send them. Everything between that
transport and veil is the SDK's own code, so the objects and events veil is tested on are
the ones an application gets.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from types import ModuleType
from typing import Any

MODEL = "test-model"


def http_module(sdk: ModuleType) -> ModuleType:
    """The HTTP library an SDK is built on (httpx, or httpx2 in newer releases)."""
    for base in sdk.DefaultHttpxClient.__mro__[1:]:
        root = base.__module__.split(".")[0]
        if root.startswith("httpx"):
            return importlib.import_module(root)
    raise RuntimeError(f"can't tell which HTTP library {sdk.__name__} uses")


class Wire:
    """A mock transport: records every request body, answers with ``reply(body)``."""

    def __init__(self, sdk: ModuleType, reply: Callable[[dict[str, Any]], Any]) -> None:
        self.http = http_module(sdk)
        self.reply = reply
        self.requests: list[dict[str, Any]] = []

    def _handle(self, request: Any) -> Any:
        body = json.loads(request.content)
        self.requests.append(body)
        answer = self.reply(body)
        if isinstance(answer, list):  # a stream of events
            return self.http.Response(
                200, headers={"content-type": "text/event-stream"}, content=sse(answer)
            )
        return self.http.Response(200, json=answer)

    def client(self) -> Any:
        return self.http.Client(transport=self.http.MockTransport(self._handle))

    def async_client(self) -> Any:
        return self.http.AsyncClient(transport=self.http.MockTransport(self._handle))

    def sent(self) -> str:
        """Everything that went to the API, as one string to search for leaks."""
        return json.dumps(self.requests, ensure_ascii=False)


def sse(events: list[Any]) -> bytes:
    """Events as a server-sent event stream. A dict with a ``type`` gets an ``event:`` line
    (Anthropic, Responses); the string ``"[DONE]"`` is Chat Completions' terminator."""
    out = []
    for event in events:
        if isinstance(event, str):
            out.append(f"data: {event}\n\n")
        elif "type" in event:
            out.append(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n")
        else:
            out.append(f"data: {json.dumps(event)}\n\n")
    return "".join(out).encode()


# ---------------------------------------------------------------- Anthropic Messages


def anthropic_message(
    blocks: list[dict[str, Any]], stop_reason: str = "end_turn"
) -> dict[str, Any]:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 20},
    }


def anthropic_stream(blocks: list[tuple[str, list[str]]]) -> list[dict[str, Any]]:
    """The event stream for a message whose content blocks are given as
    ``("text", [chunks...])``, ``("tool_use", [partial JSON...])`` or
    ``("thinking", [chunks...])``."""
    start = anthropic_message([], stop_reason="end_turn") | {"stop_reason": None}
    events: list[dict[str, Any]] = [{"type": "message_start", "message": start}]
    for index, (kind, chunks) in enumerate(blocks):
        if kind == "text":
            block: dict[str, Any] = {"type": "text", "text": ""}
            deltas = [{"type": "text_delta", "text": c} for c in chunks]
        elif kind == "tool_use":
            block = {"type": "tool_use", "id": f"toolu_{index}", "name": "send_email", "input": {}}
            deltas = [{"type": "input_json_delta", "partial_json": c} for c in chunks]
        else:
            block = {"type": "thinking", "thinking": "", "signature": ""}
            deltas = [{"type": "thinking_delta", "thinking": c} for c in chunks]
            deltas.append({"type": "signature_delta", "signature": "c2lnbmF0dXJl"})
        events.append({"type": "content_block_start", "index": index, "content_block": block})
        events.extend({"type": "content_block_delta", "index": index, "delta": d} for d in deltas)
        events.append({"type": "content_block_stop", "index": index})
    events.append(
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 20},
        }
    )
    events.append({"type": "message_stop"})
    return events


# ---------------------------------------------------------------- OpenAI Chat Completions


def chat_completion(content: str | None, tool_arguments: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_arguments is not None:
        message["tool_calls"] = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "send_email", "arguments": tool_arguments},
            }
        ]
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def chat_chunk(*choices: dict[str, Any], usage: dict[str, int] | None = None) -> dict[str, Any]:
    chunk: dict[str, Any] = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": MODEL,
        "choices": list(choices),
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def choice_delta(index: int = 0, finish: str | None = None, **delta: Any) -> dict[str, Any]:
    return {"index": index, "delta": delta, "finish_reason": finish}


def tool_delta(index: int, arguments: str, first: bool = False) -> dict[str, Any]:
    call: dict[str, Any] = {"index": index, "function": {"arguments": arguments}}
    if first:
        call |= {"id": f"call_{index}", "type": "function"}
        call["function"]["name"] = "send_email"
    return call


# ---------------------------------------------------------------- OpenAI Responses


def response_object(
    status: str, text: str | None = None, arguments: str | None = None
) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    if text is not None:
        output.append(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    if arguments is not None:
        output.append(
            {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_1",
                "name": "send_email",
                "arguments": arguments,
                "status": "completed",
            }
        )
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": MODEL,
        "status": status,
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


def responses_stream(chunks: list[str], argument_chunks: list[str]) -> list[dict[str, Any]]:
    """The event stream of a response with one text message and one function call."""
    text, arguments = "".join(chunks), "".join(argument_chunks)
    part = {"type": "output_text", "text": "", "annotations": []}
    message = {"id": "msg_1", "type": "message", "role": "assistant"}
    call = {"id": "fc_1", "type": "function_call", "call_id": "call_1", "name": "send_email"}
    at = {"item_id": "msg_1", "output_index": 0, "content_index": 0}
    events: list[dict[str, Any]] = [
        {"type": "response.created", "response": response_object("in_progress")},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": message | {"status": "in_progress", "content": []},
        },
        {"type": "response.content_part.added", **at, "part": part},
    ]
    events += [
        {"type": "response.output_text.delta", **at, "delta": c, "logprobs": []} for c in chunks
    ]
    events += [
        {"type": "response.output_text.done", **at, "text": text, "logprobs": []},
        {"type": "response.content_part.done", **at, "part": part | {"text": text}},
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": message | {"status": "completed", "content": [part | {"text": text}]},
        },
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": call | {"arguments": "", "status": "in_progress"},
        },
    ]
    events += [
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_1",
            "output_index": 1,
            "delta": c,
        }
        for c in argument_chunks
    ]
    events += [
        {
            "type": "response.function_call_arguments.done",
            "item_id": "fc_1",
            "output_index": 1,
            "arguments": arguments,
            "name": "send_email",
        },
        {
            "type": "response.output_item.done",
            "output_index": 1,
            "item": call | {"arguments": arguments, "status": "completed"},
        },
        {"type": "response.completed", "response": response_object("completed", text, arguments)},
    ]
    for number, event in enumerate(events):
        event["sequence_number"] = number
    return events
