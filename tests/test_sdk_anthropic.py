"""veil's Anthropic wrapper over the real SDK.

The SDK is given an HTTP client whose transport answers in the Messages API's wire format
(``tests/sdk_wire.py``), so every message, event and snapshot veil handles here was built by
the SDK itself, sync and async. No network, no API key.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.sdk_wire import MODEL, Wire, anthropic_message, anthropic_stream

anthropic = pytest.importorskip("anthropic")

from veil.integrations.anthropic import (  # noqa: E402
    AnthropicVeil,
    AsyncAnthropicVeil,
    AsyncVeilEventStream,
    VeilEventStream,
)

PROMPT = [{"role": "user", "content": "Email alice@example.com and bob@example.org."}]
PII = ("alice@example.com", "bob@example.org")
#: What the model writes back: it has only ever seen the surrogates.
REPLY = "Mailing ⟨EMAIL_1⟩ first, then ⟨EMAIL_2⟩."
RESTORED = "Mailing alice@example.com first, then bob@example.org."
#: The same reply as the API might chunk it, with surrogates split across chunks.
CHUNKS = ["Mailing ⟨EM", "AIL_1⟩ first, th", "en ⟨EMAIL_2", "⟩."]


def sync_veil(reply: Any) -> tuple[AnthropicVeil, Wire]:
    wire = Wire(anthropic, reply if callable(reply) else lambda body: reply)
    client = anthropic.Anthropic(api_key="test", http_client=wire.client(), max_retries=0)
    return AnthropicVeil(client), wire


def async_veil(reply: Any) -> tuple[AsyncAnthropicVeil, Wire]:
    wire = Wire(anthropic, reply if callable(reply) else lambda body: reply)
    client = anthropic.AsyncAnthropic(
        api_key="test", http_client=wire.async_client(), max_retries=0
    )
    return AsyncAnthropicVeil(client), wire


def dumped(event: Any) -> str:
    return json.dumps(event.model_dump(mode="json"), ensure_ascii=False)


def assert_nothing_real_was_sent(wire: Wire) -> None:
    sent = wire.sent()
    assert "⟨EMAIL_1⟩" in sent
    for value in PII:
        assert value not in sent


class TestCreate:
    def test_the_request_is_masked_and_the_message_restored(self) -> None:
        veil, wire = sync_veil(anthropic_message([{"type": "text", "text": REPLY}]))
        message = veil.create(model=MODEL, max_tokens=64, messages=PROMPT)
        assert isinstance(message, anthropic.types.Message)
        assert message.content[0].text == RESTORED
        assert_nothing_real_was_sent(wire)

    def test_stream_true_is_restored_too(self) -> None:
        # `create(stream=True)` returns the SDK's raw event iterator. Until 0.4.0 veil
        # handed it back as it was: the request masked, the reply full of surrogates.
        veil, wire = sync_veil(anthropic_stream([("text", CHUNKS)]))
        stream = veil.create(model=MODEL, max_tokens=64, messages=PROMPT, stream=True)
        assert isinstance(stream, VeilEventStream)
        with stream as events:
            deltas = [e.delta.text for e in events if e.type == "content_block_delta"]
        assert "".join(deltas) == RESTORED
        assert all("⟨" not in d and "⟩" not in d for d in deltas)
        assert wire.requests[0]["stream"] is True
        assert_nothing_real_was_sent(wire)

    def test_a_restored_reply_goes_back_as_the_model_wrote_it(self) -> None:
        veil, wire = sync_veil(anthropic_message([{"type": "text", "text": REPLY}]))
        first = veil.create(model=MODEL, max_tokens=64, messages=PROMPT)
        history = [*PROMPT, {"role": "assistant", "content": first.content}]
        veil.create(
            model=MODEL, max_tokens=64, messages=[*history, {"role": "user", "content": "Thanks"}]
        )
        resent = wire.requests[1]["messages"][1]["content"]
        assert [block["text"] for block in resent] == [REPLY]
        assert_nothing_real_was_sent(wire)


class TestMessageStream:
    def test_text_stream(self) -> None:
        veil, wire = sync_veil(anthropic_stream([("text", CHUNKS)]))
        with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            pieces = list(stream.text_stream)
            assert stream.get_final_message().content[0].text == RESTORED
            assert stream.get_final_text() == RESTORED
        assert "".join(pieces) == RESTORED
        assert_nothing_real_was_sent(wire)

    def test_every_event_is_restored_including_the_sdk_s_own(self) -> None:
        # Beside the API's events the SDK yields its own: `text` (the delta and the text
        # so far) after each text delta, and snapshots on content_block_stop and
        # message_stop. An application that prints `event.text` reads those.
        veil, _ = sync_veil(anthropic_stream([("text", CHUNKS)]))
        with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            events = list(stream)
        kinds = [e.type for e in events]
        assert kinds.count("text") == len(CHUNKS) and "message_stop" in kinds
        for event in events:
            assert "⟨" not in dumped(event) and "EMAIL_" not in dumped(event), event.type

        raw = [e.delta.text for e in events if e.type == "content_block_delta"]
        helper = [e for e in events if e.type == "text"]
        assert "".join(raw) == RESTORED
        assert [e.text for e in helper] == raw
        # Each snapshot is the text delivered so far, so the last one is all of it.
        assert [e.snapshot for e in helper] == ["".join(raw[: i + 1]) for i in range(len(raw))]
        (stop,) = [e for e in events if e.type == "content_block_stop"]
        assert stop.content_block.text == RESTORED
        (end,) = [e for e in events if e.type == "message_stop"]
        assert end.message.content[0].text == RESTORED

    def test_text_held_back_at_the_end_of_a_block_is_released_before_its_stop(self) -> None:
        # The reply ends on something that could have begun a surrogate and didn't.
        chunks = ["Reach me at ⟨EMAIL_1⟩ or ⟨EM"]
        veil, _ = sync_veil(anthropic_stream([("text", chunks)]))
        with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            events = list(stream)
        kinds = [e.type for e in events]
        raw = [e.delta.text for e in events if e.type == "content_block_delta"]
        assert raw == ["Reach me at alice@example.com or ", "⟨EM"]
        assert [e.text for e in events if e.type == "text"] == raw
        assert [e.snapshot for e in events if e.type == "text"][
            -1
        ] == "Reach me at alice@example.com or ⟨EM"
        # ... delta, text, delta (released), text (released), content_block_stop
        stop = kinds.index("content_block_stop")
        assert kinds[stop - 2 : stop] == ["content_block_delta", "text"]

    def test_each_text_block_has_its_own_restorer(self) -> None:
        blocks = [("text", ["First ⟨EM"]), ("text", ["AIL_1⟩ second ⟨EMAIL_2⟩"])]
        veil, _ = sync_veil(anthropic_stream(blocks))
        with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            events = list(stream)
            final = stream.get_final_message()
        by_block: dict[int, str] = {}
        for e in events:
            if e.type == "content_block_delta":
                by_block[e.index] = by_block.get(e.index, "") + e.delta.text
        # A fragment at the end of one block does not complete in the next.
        assert by_block == {0: "First ⟨EM", 1: "AIL_1⟩ second bob@example.org"}
        assert [b.text for b in final.content] == ["First ⟨EM", "AIL_1⟩ second bob@example.org"]

    def test_tool_input_is_restored_as_it_streams_and_when_it_is_whole(self) -> None:
        # The model escapes the surrogate's brackets in one place and not in the other,
        # and the API cuts the JSON inside a surrogate.
        fragments = ['{"to": "\\u27e8EMA', 'IL_1\\u27e9", "cc": ["⟨EMAIL_2', '⟩"], "urgent": true}']
        veil, _ = sync_veil(anthropic_stream([("text", ["Sending."]), ("tool_use", fragments)]))
        with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            events = list(stream)
            final = stream.get_final_message()
        expected = {"to": "alice@example.com", "cc": ["bob@example.org"], "urgent": True}
        raw = "".join(
            e.delta.partial_json
            for e in events
            if e.type == "content_block_delta" and e.delta.type == "input_json_delta"
        )
        assert json.loads(raw) == expected
        helper = [e for e in events if e.type == "input_json"]
        assert json.loads("".join(e.partial_json for e in helper)) == expected
        assert helper[-1].snapshot == expected
        tool_stop = [e for e in events if e.type == "content_block_stop"][-1]
        assert tool_stop.content_block.input == expected
        assert final.content[1].input == expected
        for event in events:
            assert "EMAIL_" not in dumped(event), event.type

    def test_thinking_passes_through_as_the_model_signed_it(self) -> None:
        if not hasattr(anthropic.types, "ThinkingDelta"):
            pytest.skip("this anthropic SDK predates thinking blocks")
        blocks = [("thinking", ["The user means ⟨EMAIL_1⟩."]), ("text", ["Mailing ⟨EMAIL_1⟩."])]
        veil, _ = sync_veil(anthropic_stream(blocks))
        with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            events = list(stream)
            final = stream.get_final_message()
        thinking = [
            e.delta.thinking
            for e in events
            if e.type == "content_block_delta" and e.delta.type == "thinking_delta"
        ]
        assert thinking == ["The user means ⟨EMAIL_1⟩."]
        assert final.content[0].thinking == "The user means ⟨EMAIL_1⟩."
        assert final.content[1].text == "Mailing alice@example.com."

    def test_what_veil_does_not_wrap_is_the_sdk_stream_s(self) -> None:
        veil, _ = sync_veil(anthropic_stream([("text", CHUNKS)]))
        with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            assert stream.response.status_code == 200
            stream.until_done()
            assert stream.current_message_snapshot.content[0].text == RESTORED

    @settings(max_examples=40, deadline=None)
    @given(cuts=st.lists(st.integers(min_value=1, max_value=len(REPLY) - 1), max_size=12))
    def test_however_the_api_chunks_the_reply_the_events_spell_the_restored_text(
        self, cuts: list[int]
    ) -> None:
        bounds = [0, *sorted(set(cuts)), len(REPLY)]
        chunks = [REPLY[a:b] for a, b in zip(bounds, bounds[1:], strict=False)]
        veil, _ = sync_veil(anthropic_stream([("text", chunks)]))
        with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            events = list(stream)
        assert "".join(e.text for e in events if e.type == "text") == RESTORED
        assert "".join(e.delta.text for e in events if e.type == "content_block_delta") == RESTORED


class TestAsync:
    def test_create(self) -> None:
        async def run() -> None:
            veil, wire = async_veil(anthropic_message([{"type": "text", "text": REPLY}]))
            message = await veil.create(model=MODEL, max_tokens=64, messages=PROMPT)
            assert message.content[0].text == RESTORED
            assert_nothing_real_was_sent(wire)

        asyncio.run(run())

    def test_stream_text_events_and_final_message(self) -> None:
        async def run() -> None:
            veil, wire = async_veil(anthropic_stream([("text", CHUNKS)]))
            async with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
                pieces = [text async for text in stream.text_stream]
                final = await stream.get_final_message()
                assert await stream.get_final_text() == RESTORED
            assert "".join(pieces) == RESTORED
            assert final.content[0].text == RESTORED

            async with veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
                events = [event async for event in stream]
            assert "".join(e.text for e in events if e.type == "text") == RESTORED
            for event in events:
                assert "EMAIL_" not in dumped(event), event.type
            assert_nothing_real_was_sent(wire)

        asyncio.run(run())

    def test_create_with_stream_true(self) -> None:
        async def run() -> None:
            veil, _ = async_veil(anthropic_stream([("text", CHUNKS)]))
            stream = await veil.create(model=MODEL, max_tokens=64, messages=PROMPT, stream=True)
            assert isinstance(stream, AsyncVeilEventStream)
            async with stream as events:
                deltas = [e.delta.text async for e in events if e.type == "content_block_delta"]
            assert "".join(deltas) == RESTORED

        asyncio.run(run())


class TestClientKinds:
    def test_each_wrapper_refuses_the_other_kind_of_client(self) -> None:
        # The sync wrapper around an async client masked the request and returned the
        # SDK's coroutine untouched: awaited, a reply full of surrogates and no error.
        with pytest.raises(TypeError, match="use AsyncAnthropicVeil"):
            AnthropicVeil(anthropic.AsyncAnthropic(api_key="test"))
        with pytest.raises(TypeError, match="use AnthropicVeil"):
            AsyncAnthropicVeil(anthropic.Anthropic(api_key="test"))
