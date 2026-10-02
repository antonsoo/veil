"""veil's OpenAI wrapper over the real SDK: Chat Completions and the Responses API.

The SDK is given an HTTP client whose transport answers in the APIs' wire format
(``tests/sdk_wire.py``), so every completion, chunk and event veil handles here was built
by the SDK itself, sync and async. No network, no API key.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.sdk_wire import (
    MODEL,
    Wire,
    chat_chunk,
    chat_completion,
    choice_delta,
    response_object,
    responses_stream,
    tool_delta,
)

openai = pytest.importorskip("openai")

from veil.integrations.openai import (  # noqa: E402
    AsyncOpenAIVeil,
    AsyncOpenAIVeilStream,
    OpenAIVeil,
    OpenAIVeilStream,
)
from veil.integrations.openai_responses import (  # noqa: E402
    AsyncOpenAIResponsesStream,
    OpenAIResponsesStream,
)

PROMPT = [{"role": "user", "content": "Email alice@example.com and bob@example.org."}]
PII = ("alice@example.com", "bob@example.org")
REPLY = "Mailing ⟨EMAIL_1⟩ first, then ⟨EMAIL_2⟩."
RESTORED = "Mailing alice@example.com first, then bob@example.org."
CHUNKS = ["Mailing ⟨EM", "AIL_1⟩ first, th", "en ⟨EMAIL_2", "⟩."]
ARGUMENTS = ['{"to": "\\u27e8EMA', 'IL_1\\u27e9", "cc": ["⟨EMAIL_2', '⟩"]}']
RESTORED_ARGUMENTS = {"to": "alice@example.com", "cc": ["bob@example.org"]}
DONE = "[DONE]"


def content_stream(chunks: list[str], finish: str = "stop") -> list[Any]:
    return [
        chat_chunk(choice_delta(role="assistant", content="")),
        *[chat_chunk(choice_delta(content=c)) for c in chunks],
        chat_chunk(choice_delta(finish=finish)),
        DONE,
    ]


def sync_veil(reply: Any) -> tuple[OpenAIVeil, Wire]:
    wire = Wire(openai, reply if callable(reply) else lambda body: reply)
    return OpenAIVeil(openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0)), wire


def async_veil(reply: Any) -> tuple[AsyncOpenAIVeil, Wire]:
    wire = Wire(openai, reply if callable(reply) else lambda body: reply)
    client = openai.AsyncOpenAI(api_key="test", http_client=wire.async_client(), max_retries=0)
    return AsyncOpenAIVeil(client), wire


def assert_nothing_real_was_sent(wire: Wire) -> None:
    sent = wire.sent()
    assert "⟨EMAIL_1⟩" in sent
    for value in PII:
        assert value not in sent


def text_of(chunks: list[Any], index: int = 0) -> str:
    return "".join(
        choice.delta.content or ""
        for chunk in chunks
        for choice in chunk.choices
        if choice.index == index
    )


class TestChatCompletions:
    def test_create(self) -> None:
        veil, wire = sync_veil(chat_completion(REPLY, "".join(ARGUMENTS)))
        completion = veil.create(model=MODEL, messages=PROMPT)
        message = completion.choices[0].message
        assert message.content == RESTORED
        assert json.loads(message.tool_calls[0].function.arguments) == RESTORED_ARGUMENTS
        assert_nothing_real_was_sent(wire)

    def test_create_with_stream_true_is_restored(self) -> None:
        # The usual way to stream with this SDK. Until 0.4.0 `create` handed the raw
        # stream back: the request masked, the reply full of surrogates.
        veil, wire = sync_veil(content_stream(CHUNKS))
        stream = veil.create(model=MODEL, messages=PROMPT, stream=True)
        assert isinstance(stream, OpenAIVeilStream)
        with stream as chunks:
            seen = list(chunks)
        assert text_of(seen) == RESTORED
        assert all("⟨" not in (c.choices[0].delta.content or "") for c in seen)
        assert wire.requests[0]["stream"] is True
        assert_nothing_real_was_sent(wire)

    def test_two_choices_streamed_together_do_not_mix(self) -> None:
        # n=2: the two choices' chunks interleave, each cut inside a surrogate. One
        # restorer for both stitched the fragments together across choices.
        stream = [
            chat_chunk(choice_delta(0, role="assistant", content="")),
            chat_chunk(choice_delta(1, role="assistant", content="")),
            chat_chunk(choice_delta(0, content="First: ⟨EM")),
            chat_chunk(choice_delta(1, content="Second: ⟨EMAIL")),
            chat_chunk(choice_delta(0, content="AIL_1⟩.")),
            chat_chunk(choice_delta(1, content="_2⟩.")),
            chat_chunk(choice_delta(0, finish="stop"), choice_delta(1, finish="stop")),
            DONE,
        ]
        veil, wire = sync_veil(stream)
        seen = list(veil.stream(model=MODEL, messages=PROMPT, n=2))
        assert text_of(seen, 0) == "First: alice@example.com."
        assert text_of(seen, 1) == "Second: bob@example.org."
        assert wire.requests[0]["n"] == 2

    def test_held_back_text_arrives_with_the_finish_reason_not_after_it(self) -> None:
        # The reply stops (length) on what could have begun a surrogate. With
        # stream_options.include_usage a usage-only chunk follows the last choice chunk.
        stream = [
            chat_chunk(choice_delta(role="assistant", content="")),
            chat_chunk(choice_delta(content="Use ⟨EMAIL_1⟩ or ⟨EM")),
            chat_chunk(choice_delta(finish="length")),
            chat_chunk(usage={"prompt_tokens": 9, "completion_tokens": 7, "total_tokens": 16}),
            DONE,
        ]
        veil, _ = sync_veil(stream)
        seen = list(
            veil.stream(model=MODEL, messages=PROMPT, stream_options={"include_usage": True})
        )
        shape = [
            (c.choices[0].delta.content, c.choices[0].finish_reason)
            if c.choices
            else ("usage", c.usage.total_tokens)
            for c in seen
        ]
        assert shape == [
            ("", None),
            ("Use alice@example.com or ", None),
            ("⟨EM", "length"),
            ("usage", 16),
        ]

    def test_a_stream_cut_off_still_releases_what_was_held(self) -> None:
        stream = [
            chat_chunk(choice_delta(role="assistant", content="")),
            chat_chunk(choice_delta(content="Use ⟨EMAIL_1⟩ or ⟨EM")),
            DONE,  # no finish_reason: the connection ended early
        ]
        veil, _ = sync_veil(stream)
        seen = list(veil.stream(model=MODEL, messages=PROMPT))
        assert text_of(seen) == "Use alice@example.com or ⟨EM"
        assert type(seen[-1]) is type(seen[0])  # the release is the SDK's own chunk type

    def test_parallel_tool_calls_are_restored_by_index(self) -> None:
        stream = [
            chat_chunk(
                choice_delta(
                    role="assistant", content=None, tool_calls=[tool_delta(0, "", first=True)]
                )
            ),
            chat_chunk(choice_delta(tool_calls=[tool_delta(1, "", first=True)])),
            chat_chunk(choice_delta(tool_calls=[tool_delta(0, '{"to": "\\u27e8EMA')])),
            chat_chunk(choice_delta(tool_calls=[tool_delta(1, '{"to": "⟨EMAIL')])),
            chat_chunk(choice_delta(tool_calls=[tool_delta(0, 'IL_1\\u27e9"}')])),
            chat_chunk(choice_delta(tool_calls=[tool_delta(1, '_2⟩"}')])),
            chat_chunk(choice_delta(finish="tool_calls")),
            DONE,
        ]
        veil, _ = sync_veil(stream)
        arguments = {0: "", 1: ""}
        for chunk in veil.stream(model=MODEL, messages=PROMPT):
            for call in chunk.choices[0].delta.tool_calls or []:
                arguments[call.index] += call.function.arguments or ""
        assert json.loads(arguments[0]) == {"to": "alice@example.com"}
        assert json.loads(arguments[1]) == {"to": "bob@example.org"}

    def test_a_refusal_is_restored_like_content(self) -> None:
        stream = [
            chat_chunk(choice_delta(role="assistant", refusal="I can't write to ⟨EM")),
            chat_chunk(choice_delta(refusal="AIL_1⟩ about that.")),
            chat_chunk(choice_delta(finish="stop")),
            DONE,
        ]
        veil, _ = sync_veil(stream)
        seen = list(veil.stream(model=MODEL, messages=PROMPT))
        refusal = "".join(c.choices[0].delta.refusal or "" for c in seen)
        assert refusal == "I can't write to alice@example.com about that."

    def test_a_restored_reply_goes_back_as_the_model_wrote_it(self) -> None:
        veil, wire = sync_veil(chat_completion(REPLY))
        first = veil.create(model=MODEL, messages=PROMPT)
        history = [*PROMPT, first.choices[0].message, {"role": "user", "content": "Thanks"}]
        veil.create(model=MODEL, messages=history)
        assert wire.requests[1]["messages"][1]["content"] == REPLY
        assert_nothing_real_was_sent(wire)

    @settings(max_examples=40, deadline=None)
    @given(cuts=st.lists(st.integers(min_value=1, max_value=len(REPLY) - 1), max_size=12))
    def test_however_the_api_chunks_the_reply_the_stream_spells_the_restored_text(
        self, cuts: list[int]
    ) -> None:
        bounds = [0, *sorted(set(cuts)), len(REPLY)]
        chunks = [REPLY[a:b] for a, b in zip(bounds, bounds[1:], strict=False)]
        veil, _ = sync_veil(content_stream(chunks))
        assert text_of(list(veil.stream(model=MODEL, messages=PROMPT))) == RESTORED


class TestResponses:
    def test_create_response(self) -> None:
        veil, wire = sync_veil(response_object("completed", REPLY, "".join(ARGUMENTS)))
        response = veil.create_response(
            model=MODEL, input="Email alice@example.com and bob@example.org."
        )
        assert response.output_text == RESTORED
        assert json.loads(response.output[1].arguments) == RESTORED_ARGUMENTS
        assert_nothing_real_was_sent(wire)

    @pytest.mark.parametrize("via_create", [False, True])
    def test_streamed_events_are_restored(self, via_create: bool) -> None:
        veil, wire = sync_veil(responses_stream(CHUNKS, ARGUMENTS))
        kwargs = {"model": MODEL, "input": "Email alice@example.com and bob@example.org."}
        stream = (
            veil.create_response(**kwargs, stream=True)
            if via_create
            else veil.stream_response(**kwargs)
        )
        assert isinstance(stream, OpenAIResponsesStream)
        events = list(stream)
        for event in events:
            dumped = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            assert "EMAIL_" not in dumped, event.type
        text = "".join(e.delta for e in events if e.type == "response.output_text.delta")
        arguments = "".join(
            e.delta for e in events if e.type == "response.function_call_arguments.delta"
        )
        assert text == RESTORED
        assert json.loads(arguments) == RESTORED_ARGUMENTS
        assert events[-1].type == "response.completed"
        assert events[-1].response.output_text == RESTORED
        assert_nothing_real_was_sent(wire)


class TestAsync:
    def test_chat_create_and_both_ways_to_stream(self) -> None:
        async def run() -> None:
            veil, wire = async_veil(
                lambda body: (
                    content_stream(CHUNKS) if body.get("stream") else chat_completion(REPLY)
                )
            )
            completion = await veil.create(model=MODEL, messages=PROMPT)
            assert completion.choices[0].message.content == RESTORED

            stream = await veil.stream(model=MODEL, messages=PROMPT)
            assert isinstance(stream, AsyncOpenAIVeilStream)
            assert text_of([chunk async for chunk in stream]) == RESTORED

            stream = await veil.create(model=MODEL, messages=PROMPT, stream=True)
            async with stream as chunks:
                assert text_of([chunk async for chunk in chunks]) == RESTORED
            assert_nothing_real_was_sent(wire)

        asyncio.run(run())

    def test_responses_create_and_stream(self) -> None:
        async def run() -> None:
            def reply(body: dict[str, Any]) -> Any:
                if body.get("stream"):
                    return responses_stream(CHUNKS, ARGUMENTS)
                return response_object("completed", REPLY, "".join(ARGUMENTS))

            veil, wire = async_veil(reply)
            response = await veil.create_response(model=MODEL, input=PROMPT[0]["content"])
            assert response.output_text == RESTORED

            stream = await veil.stream_response(model=MODEL, input=PROMPT[0]["content"])
            assert isinstance(stream, AsyncOpenAIResponsesStream)
            events = [event async for event in stream]
            text = "".join(e.delta for e in events if e.type == "response.output_text.delta")
            assert text == RESTORED
            assert events[-1].response.output_text == RESTORED
            with pytest.raises(TypeError, match="async for"):
                iter(stream)
            assert_nothing_real_was_sent(wire)

        asyncio.run(run())


class TestClientKinds:
    def test_each_wrapper_refuses_the_other_kind_of_client(self) -> None:
        with pytest.raises(TypeError, match="use AsyncOpenAIVeil"):
            OpenAIVeil(openai.AsyncOpenAI(api_key="test"))
        with pytest.raises(TypeError, match="use OpenAIVeil"):
            AsyncOpenAIVeil(openai.OpenAI(api_key="test"))
