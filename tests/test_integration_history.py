"""Multi-turn history through the wrappers: what goes back to the API on the
next request after the application appends the (restored) assistant turn.

Two properties matter. No real value may reach the API - including the real
arguments veil restored into a tool call for the application to execute.
And an assistant turn must go back exactly as the model produced it: any
difference is an edit to an earlier turn, which restarts the prompt cache and,
on current Claude models, invalidates the signatures of later thinking blocks.
These tests use the real Anthropic SDK response types (no network calls).
"""

from __future__ import annotations

import json
from typing import Any

from anthropic.types import Message

from veil.integrations._common import ReplayCache
from veil.integrations.anthropic import AnthropicVeil, mask_messages
from veil.integrations.openai import OpenAIVeil
from veil.masker import Masker


def _message(content: list[dict[str, Any]]) -> Message:
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


class RecordingMessages:
    """Answers each create() with the next scripted reply, built from the masked request it saw."""

    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        reply = self.replies[len(self.requests) - 1]
        return reply(kwargs) if callable(reply) else reply


class RecordingClient:
    def __init__(self, replies: list[Any]) -> None:
        self.messages = RecordingMessages(replies)


def _sent(request: dict[str, Any]) -> str:
    def default(obj: Any) -> Any:
        return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else str(obj)

    return json.dumps(request["messages"], default=default)


def _first_surrogate(request: dict[str, Any]) -> str:
    text = request["messages"][0]["content"]
    return text.split("Email ")[1].split(" ")[0]


def _tool_call_turn(request: dict[str, Any]) -> Message:
    surrogate = _first_surrogate(request)
    return _message(
        [
            {"type": "thinking", "thinking": "", "signature": "c2lnbmF0dXJl"},
            # The model also writes a support address of its own: not in the vault, but it looks like PII.
            {"type": "text", "text": f"Emailing {surrogate}; replies go to help@example.org."},
            {"type": "tool_use", "id": "toolu_1", "name": "send_email", "input": {"to": surrogate}},
        ]
    )


DONE = _message([{"type": "text", "text": "Done."}])


def _conversation(client: RecordingClient, store: str = "content") -> AnthropicVeil:
    veil = AnthropicVeil(client)
    history: list[dict[str, Any]] = [
        {"role": "user", "content": "Email alice@example.com about invoice 4471."}
    ]
    first = veil.create(model="claude-opus-5-5", max_tokens=100, messages=history)
    assert first.content[2].input == {"to": "alice@example.com"}  # the app executes the real call
    if store == "content":
        assistant: Any = first.content
    elif store == "dumped":
        assistant = [b.model_dump(mode="json", exclude_none=True) for b in first.content]
    else:
        assistant = first.content[1].text
    history += [
        {"role": "assistant", "content": assistant},
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "sent"}],
        },
    ]
    veil.create(model="claude-opus-5-5", max_tokens=100, messages=history)
    return veil


def test_restored_tool_arguments_never_go_back_to_the_api() -> None:
    client = RecordingClient([_tool_call_turn, DONE])
    _conversation(client)
    assert "alice@example.com" not in _sent(client.messages.requests[1])


def test_the_assistant_turn_goes_back_exactly_as_the_model_produced_it() -> None:
    for store in ("content", "dumped"):
        client = RecordingClient([_tool_call_turn, DONE])
        _conversation(client, store)
        produced = _tool_call_turn(client.messages.requests[0]).model_dump(
            mode="json", exclude_none=True
        )["content"]
        resent = client.messages.requests[1]["messages"][1]["content"]
        resent_plain = [
            b.model_dump(mode="json", exclude_none=True) if hasattr(b, "model_dump") else b
            for b in resent
        ]
        assert resent_plain == produced, store


def test_an_assistant_turn_stored_as_plain_text_is_replayed_too() -> None:
    client = RecordingClient([_tool_call_turn, DONE])
    _conversation(client, store="text")
    resent = client.messages.requests[1]["messages"][1]["content"]
    assert resent.startswith("Emailing ⟨EMAIL_1⟩; replies go to help@example.org.")


def test_without_replay_a_prior_tool_call_is_still_masked() -> None:
    masker = Masker()
    masker.mask("alice@example.com")
    history = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "t",
                    "name": "send",
                    "input": {"to": ["alice@example.com"]},
                }
            ],
        }
    ]
    masked = mask_messages(history, masker)
    assert masked[0]["content"][0]["input"] == {"to": ["⟨EMAIL_1⟩"]}


def test_an_edited_assistant_turn_is_masked_not_replayed() -> None:
    client = RecordingClient([_tool_call_turn, DONE])
    veil = AnthropicVeil(client)
    history: list[dict[str, Any]] = [
        {"role": "user", "content": "Email alice@example.com about invoice 4471."}
    ]
    first = veil.create(model="claude-opus-5-5", max_tokens=100, messages=history)
    edited = first.content[1].model_copy(
        update={"text": first.content[1].text + " Also cc alice@example.com."}
    )
    history.append({"role": "assistant", "content": [edited]})
    veil.create(model="claude-opus-5-5", max_tokens=100, messages=history)
    assert "alice@example.com" not in _sent(client.messages.requests[1])


def test_replay_cache_is_bounded() -> None:
    cache = ReplayCache(max_entries=3)
    for i in range(5):
        cache.remember(f"restored {i}", f"original {i}")
    assert len(cache) == 3
    assert cache.original_for("restored 0") is None
    assert cache.original_for("restored 4") == "original 4"


class RecordingCompletions:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        reply = self.replies[len(self.requests) - 1]
        return reply(kwargs) if callable(reply) else reply


class OpenAIClient:
    def __init__(self, replies: list[Any]) -> None:
        self.chat = type("Chat", (), {"completions": RecordingCompletions(replies)})()


def test_openai_assistant_turn_is_replayed_exactly() -> None:
    def reply(request: dict[str, Any]) -> dict[str, Any]:
        surrogate = request["messages"][0]["content"].split("Email ")[1].split(" ")[0]
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"Emailing {surrogate}; replies go to help@example.org.",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "send_email",
                                    "arguments": json.dumps({"to": surrogate}),
                                },
                            }
                        ],
                    },
                }
            ]
        }

    client = OpenAIClient(
        [reply, {"choices": [{"index": 0, "message": {"role": "assistant", "content": "Done."}}]}]
    )
    veil = OpenAIVeil(client)
    history: list[dict[str, Any]] = [
        {"role": "user", "content": "Email alice@example.com about invoice 4471."}
    ]
    first = veil.create(model="gpt-6-sol", messages=history)
    message = first["choices"][0]["message"]
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
        "to": "alice@example.com"
    }
    history += [message, {"role": "tool", "tool_call_id": "c1", "content": "sent"}]
    veil.create(model="gpt-6-sol", messages=history)
    requests = client.chat.completions.requests
    assert "alice@example.com" not in json.dumps(requests[1]["messages"])
    assert requests[1]["messages"][1] == reply(requests[0])["choices"][0]["message"]
