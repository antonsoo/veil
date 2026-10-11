"""Streaming state follows content block indices, including through text helpers."""

import asyncio

import pytest

from tests.sdk_wire import MODEL, anthropic_message, anthropic_stream
from tests.test_sdk_anthropic import PROMPT, async_veil, sync_veil

TOKEN = "⟨EMAIL_1⟩"


@pytest.mark.parametrize("cut", range(1, len(TOKEN)))
@pytest.mark.parametrize("asynchronous", [False, True])
def test_every_cross_block_split_stays_literal_in_stream_and_final_text(cut, asynchronous):
    blocks = [("text", [TOKEN[:cut]]), ("text", [TOKEN[cut:]])]

    async def run():
        veil, _ = async_veil(anthropic_stream(blocks))
        async with veil.client, veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            text = "".join([piece async for piece in stream.text_stream])
            assert text == TOKEN
            assert await stream.get_final_text() == TOKEN

    if asynchronous:
        asyncio.run(run())
    else:
        veil, _ = sync_veil(anthropic_stream(blocks))
        with veil.client, veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            assert "".join(stream.text_stream) == TOKEN
            assert stream.get_final_text() == TOKEN


@pytest.mark.parametrize("asynchronous", [False, True])
def test_partial_consumption_keeps_pending_text_when_switching_to_events(asynchronous):
    events = anthropic_stream([("text", ["First ⟨EM", "AIL_1⟩"]), ("text", ["then ⟨EM"])])

    async def run():
        veil, _ = async_veil(events)
        async with veil.client, veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            text = stream.text_stream
            first = await anext(text)
            remaining = [event async for event in stream]
            assert first == "First "
            assert (
                "".join(e.delta.text for e in remaining if e.type == "content_block_delta")
                == "alice@example.comthen ⟨EM"
            )

    if asynchronous:
        asyncio.run(run())
    else:
        veil, _ = sync_veil(events)
        with veil.client, veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            text = stream.text_stream
            first = next(text)
            remaining = list(stream)
            assert first == "First "
            assert (
                "".join(e.delta.text for e in remaining if e.type == "content_block_delta")
                == "alice@example.comthen ⟨EM"
            )


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "blocks, expected",
    [
        ([("text", ["⟨EM"]), ("tool_use", ['{"to":"⟨EMAIL_2⟩"}']), ("text", ["AIL_1⟩"])], TOKEN),
        ([("text", [])], ""),
        ([("tool_use", ["{}"])], None),
    ],
)
def test_get_final_text_can_drain_without_flattening_raw_blocks(blocks, expected, asynchronous):
    async def run():
        veil, _ = async_veil(anthropic_stream(blocks))
        async with veil.client, veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            if expected is None:
                with pytest.raises(RuntimeError, match="text content block"):
                    await stream.get_final_text()
            else:
                assert await stream.get_final_text() == expected

    if asynchronous:
        asyncio.run(run())
    else:
        veil, _ = sync_veil(anthropic_stream(blocks))
        with veil.client, veil.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
            if expected is None:
                with pytest.raises(RuntimeError, match="text content block"):
                    stream.get_final_text()
            else:
                assert stream.get_final_text() == expected


@pytest.mark.parametrize("form", ["string", "blocks"])
def test_anthropic_user_content_never_uses_assistant_replay(form):
    text = "Contact help@example.org."
    wrapper, wire = sync_veil(anthropic_message([{"type": "text", "text": text}]))
    with wrapper.client:
        reply = wrapper.create(
            model=MODEL, max_tokens=64, messages=[{"role": "user", "content": "Hello"}]
        )
        content = reply.content[0].text if form == "string" else reply.content
        wrapper.create(model=MODEL, max_tokens=64, messages=[{"role": "user", "content": content}])
    assert "help@example.org" not in str(wire.requests[1])
    assert "⟨EMAIL_1⟩" in str(wire.requests[1])
