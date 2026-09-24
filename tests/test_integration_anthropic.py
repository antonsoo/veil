"""Tests against fakes shaped like the Anthropic Python SDK's documented
surface (``client.messages.create`` / ``client.messages.stream`` ->
``MessageStream`` with ``.text_stream`` / ``.get_final_message()``). No
network calls, no API key — see the module docstring in
``veil.integrations.anthropic`` for why this is safe to test this way.
"""

from __future__ import annotations

from typing import Any

from veil.integrations.anthropic import AnthropicVeil, mask_messages, mask_system
from veil.masker import Masker
from veil.types import EntityType


class FakeMessages:
    def __init__(
        self, response: dict[str, Any] | None = None, stream_events: list[dict] | None = None
    ):
        self.response = response
        self.stream_events = stream_events or []
        self.last_create_kwargs: dict[str, Any] | None = None
        self.last_stream_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.last_create_kwargs = kwargs
        assert self.response is not None
        return self.response

    def stream(self, **kwargs: Any) -> FakeMessageStream:
        self.last_stream_kwargs = kwargs
        return FakeMessageStream(self.stream_events, self.response or {"content": []})


class FakeClient:
    def __init__(
        self, response: dict[str, Any] | None = None, stream_events: list[dict] | None = None
    ):
        self.messages = FakeMessages(response, stream_events)


class FakeMessageStream:
    def __init__(self, events: list[dict], final_message: dict[str, Any]):
        self._events = events
        self._final_message = final_message

    def __enter__(self) -> FakeMessageStream:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self):
        return iter(self._events)

    @property
    def text_stream(self):
        for event in self._events:
            if (
                event.get("type") == "content_block_delta"
                and event["delta"].get("type") == "text_delta"
            ):
                yield event["delta"]["text"]

    def get_final_message(self) -> dict[str, Any]:
        return self._final_message


def test_mask_messages_masks_text_blocks() -> None:
    masker = Masker()
    messages = [{"role": "user", "content": [{"type": "text", "text": "Email alice@example.com"}]}]
    masked = mask_messages(messages, masker)
    assert "alice@example.com" not in masked[0]["content"][0]["text"]


def test_mask_messages_plain_string_content() -> None:
    masker = Masker()
    messages = [{"role": "user", "content": "Call me at +1 202-555-0143"}]
    masked = mask_messages(messages, masker)
    assert "202-555-0143" not in masked[0]["content"]


def test_mask_messages_masks_tool_result_content() -> None:
    masker = Masker()
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "Customer email: alice@example.com",
                }
            ],
        }
    ]
    masked = mask_messages(messages, masker)
    assert "alice@example.com" not in masked[0]["content"][0]["content"]


def test_mask_system_string_and_list_forms() -> None:
    masker = Masker()
    assert "alice@example.com" not in mask_system("Customer: alice@example.com", masker)
    blocks = mask_system([{"type": "text", "text": "Customer: alice@example.com"}], masker)
    assert "alice@example.com" not in blocks[0]["text"]


def test_create_masks_outgoing_and_restores_response() -> None:
    masker = Masker()
    client = FakeClient(
        response={
            "content": [{"type": "text", "text": "PLACEHOLDER"}],
        }
    )
    veil_client = AnthropicVeil(client, masker=masker)

    # Capture the masked outgoing text so we can echo a realistic surrogate
    # back, simulating what the model would actually receive and repeat.
    def create(**kwargs: Any) -> dict[str, Any]:
        outgoing_text = kwargs["messages"][0]["content"]
        return {"content": [{"type": "text", "text": f"Sure, I noted: {outgoing_text}"}]}

    client.messages.create = create  # type: ignore[method-assign]

    response = veil_client.create(
        model="claude-opus-5",
        max_tokens=100,
        messages=[{"role": "user", "content": "Contact alice@example.com please"}],
    )
    assert "alice@example.com" in response["content"][0]["text"]
    assert "⟨EMAIL_1⟩" not in response["content"][0]["text"]


def test_create_restores_tool_use_input() -> None:
    masker = Masker()
    surrogate = masker.mask("alice@example.com")  # populates the vault

    client = FakeClient(
        response={
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "send_email",
                    "input": {"to": surrogate, "nested": {"cc": [surrogate]}},
                }
            ]
        }
    )
    veil_client = AnthropicVeil(client, masker=masker)
    response = veil_client.create(
        model="claude-opus-5", max_tokens=100, messages=[{"role": "user", "content": "go"}]
    )
    tool_block = response["content"][0]
    assert tool_block["input"]["to"] == "alice@example.com"
    assert tool_block["input"]["nested"]["cc"] == ["alice@example.com"]


def test_stream_text_restored_across_chunk_boundary() -> None:
    masker = Masker()
    masker.mask("alice@example.com")  # vault now maps EMAIL_1 <-> alice@example.com
    events = [
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi ⟨EM"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "AIL_1⟩, ok"}},
    ]
    client = FakeClient(stream_events=events)
    veil_client = AnthropicVeil(client, masker=masker)

    with veil_client.stream(model="claude-opus-5", max_tokens=100, messages=[]) as stream:
        text = "".join(stream.text_stream)
    assert text == "Hi alice@example.com, ok"


def test_stream_get_final_message_restores() -> None:
    masker = Masker()
    masker.mask("alice@example.com")
    surrogate = masker.vault.lookup_original(EntityType.EMAIL, "alice@example.com").surrogate
    final = {"content": [{"type": "text", "text": f"Reply: {surrogate}"}]}
    client = FakeClient(response=final, stream_events=[])
    veil_client = AnthropicVeil(client, masker=masker)

    with veil_client.stream(model="claude-opus-5", max_tokens=100, messages=[]) as stream:
        list(stream.text_stream)
        message = stream.get_final_message()
    assert message["content"][0]["text"] == "Reply: alice@example.com"
