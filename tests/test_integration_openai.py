"""Tests against fakes shaped like the OpenAI Python SDK's documented
surface: ``client.chat.completions.create(..., stream=True)`` yields
``ChatCompletionChunk``-shaped objects with ``choices[].delta.content`` and
``choices[].delta.tool_calls[].function.arguments`` (per the Context7
lookup of openai-python's streaming helpers doc, referenced when writing
``veil.integrations.openai``). No network calls, no API key.
"""

from __future__ import annotations

from typing import Any

from veil.integrations.openai import OpenAIVeil, mask_messages
from veil.masker import Masker
from veil.types import EntityType


class FakeCompletions:
    def __init__(self, response: dict[str, Any] | None = None, chunks: list[dict] | None = None):
        self.response = response
        self.chunks = chunks or []
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        if kwargs.get("stream"):
            return iter(self.chunks)
        assert self.response is not None
        return self.response


class FakeClient:
    def __init__(self, response: dict[str, Any] | None = None, chunks: list[dict] | None = None):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions(response, chunks)


def test_mask_messages_string_content() -> None:
    masker = Masker()
    messages = [{"role": "user", "content": "Email alice@example.com"}]
    masked = mask_messages(messages, masker)
    assert "alice@example.com" not in masked[0]["content"]


def test_mask_messages_preserves_tool_call_history_with_same_surrogate() -> None:
    masker = Masker()
    surrogate = masker.mask("alice@example.com")
    # Simulate resending a prior assistant turn (already restored to the
    # real value by the app) as conversation history.
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "send_email", "arguments": '{"to": "alice@example.com"}'},
                }
            ],
        }
    ]
    masked = mask_messages(messages, masker)
    args = masked[0]["tool_calls"][0]["function"]["arguments"]
    assert "alice@example.com" not in args
    assert surrogate in args  # same surrogate reused, not a new one


def test_create_masks_outgoing_and_restores_response() -> None:
    masker = Masker()

    def create(**kwargs: Any) -> dict[str, Any]:
        outgoing = kwargs["messages"][0]["content"]
        return {"choices": [{"message": {"role": "assistant", "content": f"Got: {outgoing}"}}]}

    client = FakeClient()
    client.chat.completions.create = create  # type: ignore[method-assign]
    veil_client = OpenAIVeil(client, masker=masker)

    response = veil_client.create(
        model="gpt-4o", messages=[{"role": "user", "content": "Contact alice@example.com"}]
    )
    assert "alice@example.com" in response["choices"][0]["message"]["content"]


def test_create_restores_tool_call_arguments() -> None:
    masker = Masker()
    surrogate = masker.mask("alice@example.com")
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "send_email",
                                "arguments": f'{{"to": "{surrogate}"}}',
                            },
                        }
                    ],
                }
            }
        ]
    }
    client = FakeClient(response=response)
    veil_client = OpenAIVeil(client, masker=masker)
    result = veil_client.create(model="gpt-4o", messages=[{"role": "user", "content": "go"}])
    args = result["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert args == '{"to": "alice@example.com"}'


def test_stream_content_restored_across_chunk_boundary() -> None:
    masker = Masker()
    masker.mask("alice@example.com")
    surrogate = masker.vault.lookup_original(EntityType.EMAIL, "alice@example.com").surrogate
    half = len(surrogate) // 2
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": f"Hi {surrogate[:half]}"}}]},
        {"choices": [{"index": 0, "delta": {"content": f"{surrogate[half:]}, ok"}}]},
    ]
    client = FakeClient(chunks=chunks)
    veil_client = OpenAIVeil(client, masker=masker)

    stream = veil_client.stream(model="gpt-4o", messages=[])
    text = "".join(
        c["choices"][0]["delta"]["content"]
        for c in stream
        if c.get("choices") and c["choices"][0].get("delta", {}).get("content")
    )
    assert text == "Hi alice@example.com, ok"


def test_stream_restores_tool_call_argument_fragments_per_index() -> None:
    masker = Masker()
    masker.mask("alice@example.com")
    surrogate = masker.vault.lookup_original(EntityType.EMAIL, "alice@example.com").surrogate
    chunks = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"to": "'}}]},
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": surrogate}}]},
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"}'}}]},
                }
            ]
        },
    ]
    client = FakeClient(chunks=chunks)
    veil_client = OpenAIVeil(client, masker=masker)

    fragments = []
    for c in veil_client.stream(model="gpt-4o", messages=[]):
        calls = c.get("choices", [{}])[0].get("delta", {}).get("tool_calls")
        if calls:
            fragments.append(calls[0]["function"]["arguments"])
    assert "".join(fragments) == '{"to": "alice@example.com"}'


def test_stream_flushes_held_back_tail_at_end() -> None:
    masker = Masker()
    masker.mask("alice@example.com")
    surrogate = masker.vault.lookup_original(EntityType.EMAIL, "alice@example.com").surrogate
    # Stream ends mid-surrogate: nothing ever completes it.
    chunks = [{"choices": [{"index": 0, "delta": {"content": f"Hi {surrogate[:3]}"}}]}]
    client = FakeClient(chunks=chunks)
    veil_client = OpenAIVeil(client, masker=masker)
    text_parts = [
        c["choices"][0]["delta"]["content"]
        for c in veil_client.stream(model="gpt-4o", messages=[])
        if c.get("choices") and c["choices"][0].get("delta", {}).get("content")
    ]
    assert "".join(text_parts) == f"Hi {surrogate[:3]}"
