"""A thin wrapper around the Anthropic Python SDK that masks outgoing
messages and restores PII in the response, streaming included.

Requires the ``anthropic`` extra (``pip install "veil-pii[anthropic]"``).
This module only touches the SDK's public, documented surface
(``client.messages.create`` / ``client.messages.stream``, the
``MessageStream`` helper's events, ``text_stream`` and
``get_final_message()``). It makes no live calls and this repo has no API key;
it is tested two ways. ``tests/test_integration_anthropic.py`` uses fakes
shaped like the SDK. ``tests/test_sdk_anthropic.py`` runs the real SDK, sync
and async, over a mocked HTTP transport that answers in the API's wire format,
so the events veil sees there are the ones the SDK really builds.

**What gets masked:** every text block, tool-result content string and
``tool_use`` input value in ``messages``, and every text block in ``system``
(both the plain-string and the list-of-blocks forms). Images and other binary
content pass through untouched — veil only understands text. Thinking blocks
pass through untouched too: they carry a signature over their exact content.

**What gets restored:** every text block and tool_use ``input`` value in
the response, including from a token stream (via
:class:`veil.restore.Restorer`, so a surrogate split across chunks is still
caught).

**Streaming.** Three ways to stream, all restored:
``AnthropicVeil.stream(...).text_stream``; iterating the stream's events; and
``create(..., stream=True)``, the raw event iterator. In the events, text
deltas and tool-input JSON fragments go through a restorer per content block.
The SDK's own helper events are restored with them: ``text`` (the delta and the
text so far), ``input_json`` (the fragment and the input so far), and the
snapshots on ``content_block_stop`` and ``message_stop``. Text held back
because it might begin a surrogate is released before its block's
``content_block_stop``, as one more delta event (a copy of the block's last
one, so the SDK type is kept).

**Async.** :class:`AsyncAnthropicVeil` is the same wrapper for
``anthropic.AsyncAnthropic``. Each wrapper refuses the other kind of client:
handed an async client, the sync wrapper would mask the request and return a
coroutine it cannot restore.

**History replay:** an assistant turn veil restored comes back on the next
request with real values in it (in its text, and in the ``tool_use`` input
the application just executed). :class:`AnthropicVeil` remembers the exact
blocks the model produced and sends those instead, so the history the API
sees never changes between requests - see :class:`ReplayCache` for why that
matters for prompt caching and thinking-block signatures. A block veil never
restored (or one the application edited) is masked like any other.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator, Iterator
from dataclasses import dataclass, field
from typing import Any

from veil.integrations._common import (
    ReplayCache,
    get_field,
    mask_value,
    model_copy_with,
    needs_await,
    restore_value,
)
from veil.masker import Masker
from veil.restore import Restorer


def mask_content(content: Any, masker: Masker, replay: ReplayCache | None = None) -> Any:
    """Mask a message's ``content`` field (a string, or a list of blocks).

    With ``replay``, anything veil restored earlier is swapped back for the
    exact original instead of being re-masked.
    """
    if replay is not None and isinstance(content, str | list):
        original = replay.original_for(content)
        if original is not None:
            return original
    if isinstance(content, str):
        return masker.mask(content)
    if isinstance(content, list):
        return [_mask_block(b, masker, replay) for b in content]
    return content


def _mask_block(block: Any, masker: Masker, replay: ReplayCache | None = None) -> Any:
    if replay is not None:
        original = replay.original_for(block)
        if original is not None:
            return original
    block_type = get_field(block, "type")
    if block_type == "text":
        text = get_field(block, "text")
        if isinstance(text, str):
            return model_copy_with(block, text=masker.mask(text))
    elif block_type == "tool_result":
        result_content = get_field(block, "content")
        if result_content is not None:
            return model_copy_with(block, content=mask_content(result_content, masker))
    elif block_type == "tool_use":
        # A prior assistant turn's tool call, restored for the application to execute: without
        # this, its real arguments would go straight back to the API in the next request.
        tool_input = get_field(block, "input")
        if tool_input is not None:
            return model_copy_with(block, input=mask_value(tool_input, masker))
    return block


def mask_messages(
    messages: list[Any], masker: Masker, replay: ReplayCache | None = None
) -> list[Any]:
    return [
        model_copy_with(m, content=mask_content(get_field(m, "content"), masker, replay))
        for m in messages
    ]


def mask_system(system: Any, masker: Masker) -> Any:
    if isinstance(system, str):
        return masker.mask(system)
    if isinstance(system, list):
        return [_mask_block(b, masker) for b in system]
    return system


def _restore_block(block: Any, masker: Masker) -> Any:
    block_type = get_field(block, "type")
    if block_type == "text":
        text = get_field(block, "text")
        if isinstance(text, str):
            return model_copy_with(block, text=masker.restore(text))
    elif block_type == "tool_use":
        tool_input = get_field(block, "input")
        if tool_input is not None:
            return model_copy_with(block, input=restore_value(tool_input, masker))
    return block


def restore_message(message: Any, masker: Masker, replay: ReplayCache | None = None) -> Any:
    """Restore a full (non-streamed) response message's content blocks.

    With ``replay``, every restored block (and the restored content list, and
    each text block's restored text on its own - applications store any of
    the three as history) is remembered against the original.
    """
    content = get_field(message, "content")
    if not isinstance(content, list):
        return message
    restored = [_restore_block(b, masker) for b in content]
    if replay is not None:
        replay.remember(restored, content)
        for new, old in zip(restored, content, strict=True):
            replay.remember(new, old)
            if get_field(new, "type") == "text" and isinstance(get_field(new, "text"), str):
                replay.remember(get_field(new, "text"), get_field(old, "text"))
    return model_copy_with(message, content=restored)


@dataclass
class _Held:
    """One streamed content block: its restorer, the last delta event seen for it (the
    template for releasing held-back text) and what has been released so far."""

    restorer: Restorer
    is_text: bool
    last_delta: Any = None
    last_helper: Any = None  # the SDK's `text` / `input_json` event that followed that delta
    restored: str = ""


class EventRestorer:
    """Restores the events of one message stream, one at a time.

    It does no I/O: the sync and the async stream wrappers both feed it what the SDK
    yields and pass on what it returns. An event comes back as one event, or as several
    when held-back text has to be released ahead of it.
    """

    def __init__(self, masker: Masker, replay: ReplayCache | None = None) -> None:
        self._masker = masker
        self._replay = replay
        self._held: dict[int, _Held] = {}
        # The block and restored text of the delta just seen: the SDK follows a raw delta
        # with a helper event (`text`, `input_json`) describing the same delta.
        self._current: int | None = None
        self._piece = ""

    def _feed_delta(self, event: Any, delta: Any, field_name: str) -> Any:
        index = get_field(event, "index", 0)
        held = self._held.get(index)
        if held is None:
            is_text = field_name == "text"
            held = _Held(Restorer(self._masker.vault, json_string=not is_text), is_text)
            self._held[index] = held
        piece = held.restorer.feed(get_field(delta, field_name, "") or "")
        held.last_delta = event
        held.restored += piece
        self._current, self._piece = index, piece
        return model_copy_with(event, delta=model_copy_with(delta, **{field_name: piece}))

    def _release(self, index: int) -> list[Any]:
        """The text still held back for a block, as one more delta event (and one more
        helper event, when the stream has them)."""
        held = self._held.pop(index, None)
        if held is None:
            return []
        tail = held.restorer.flush()
        if not tail or held.last_delta is None:
            return []
        held.restored += tail
        field_name = "text" if held.is_text else "partial_json"
        delta = model_copy_with(get_field(held.last_delta, "delta"), **{field_name: tail})
        out = [model_copy_with(held.last_delta, delta=delta)]
        if held.last_helper is not None:
            if held.is_text:
                out.append(model_copy_with(held.last_helper, text=tail, snapshot=held.restored))
            else:
                out.append(model_copy_with(held.last_helper, partial_json=tail))
        return out

    def feed(self, event: Any) -> list[Any]:
        event_type = get_field(event, "type")
        if event_type == "content_block_delta":
            delta = get_field(event, "delta")
            delta_type = get_field(delta, "type")
            if delta_type == "text_delta":
                return [self._feed_delta(event, delta, "text")]
            if delta_type == "input_json_delta":
                return [self._feed_delta(event, delta, "partial_json")]
            return [event]  # thinking, signature and citation deltas pass through
        if event_type in ("text", "input_json"):
            held = self._held.get(self._current) if self._current is not None else None
            if held is None or held.is_text != (event_type == "text"):
                return [event]
            held.last_helper = event
            if held.is_text:
                return [model_copy_with(event, text=self._piece, snapshot=held.restored)]
            snapshot = restore_value(get_field(event, "snapshot"), self._masker)
            return [model_copy_with(event, partial_json=self._piece, snapshot=snapshot)]
        if event_type == "content_block_stop":
            out = self._release(get_field(event, "index", 0))
            block = get_field(event, "content_block")
            if block is not None:
                event = model_copy_with(event, content_block=_restore_block(block, self._masker))
            return [*out, event]
        if event_type == "message_stop":
            out = self.finish()
            message = get_field(event, "message")
            if message is not None:
                restored = restore_message(message, self._masker, self._replay)
                event = model_copy_with(event, message=restored)
            return [*out, event]
        return [event]

    def finish(self) -> list[Any]:
        """Release everything still held back: the stream ended, or was cut off."""
        out: list[Any] = []
        for index in list(self._held):
            out.extend(self._release(index))
        return out


class _Delegating:
    """Hands anything veil does not wrap (``close()``, ``response``, ``request_id``, ...)
    to the SDK object underneath."""

    raw: Any

    def _target(self) -> Any:
        return self.raw

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name == "raw":
            raise AttributeError(name)
        return getattr(self._target(), name)


@dataclass
class VeilEventStream(_Delegating):
    """The raw event iterator of ``client.messages.create(..., stream=True)``, restored."""

    raw: Any
    masker: Masker
    replay: ReplayCache | None = None

    def __enter__(self) -> VeilEventStream:
        if hasattr(self.raw, "__enter__"):
            self.raw.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> Any:
        if hasattr(self.raw, "__exit__"):
            return self.raw.__exit__(*exc_info)
        return None

    def __iter__(self) -> Iterator[Any]:
        events = EventRestorer(self.masker, self.replay)
        for event in self.raw:
            yield from events.feed(event)
        yield from events.finish()


@dataclass
class VeilMessageStream(_Delegating):
    """Wraps the Anthropic SDK's ``MessageStream`` (the object returned by
    ``client.messages.stream(...)``) so text and events arrive already restored.
    """

    raw: Any  # the object returned by client.messages.stream(...) (a context manager)
    masker: Masker
    replay: ReplayCache | None = None
    _restorer: Restorer = field(init=False)
    _entered: Any = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._restorer = Restorer(self.masker.vault)

    def _target(self) -> Any:
        return self._entered if self._entered is not None else self.raw

    def __enter__(self) -> VeilMessageStream:
        self._entered = self.raw.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> Any:
        return self.raw.__exit__(*exc_info)

    @property
    def text_stream(self) -> Generator[str, None, None]:
        for text in self._target().text_stream:
            restored = self._restorer.feed(text)
            if restored:
                yield restored
        tail = self._restorer.flush()
        if tail:
            yield tail

    def __iter__(self) -> Iterator[Any]:
        """Yield the SDK's events, restored (see :class:`EventRestorer`)."""
        events = EventRestorer(self.masker, self.replay)
        for event in self._target():
            yield from events.feed(event)
        yield from events.finish()

    def get_final_message(self) -> Any:
        message = self._target().get_final_message()
        return restore_message(message, self.masker, self.replay)

    def get_final_text(self) -> str:
        return self.masker.restore(self._target().get_final_text())

    @property
    def current_message_snapshot(self) -> Any:
        return restore_message(self._target().current_message_snapshot, self.masker)


@dataclass
class AsyncVeilEventStream(_Delegating):
    """The raw event stream of ``await client.messages.create(..., stream=True)`` on an
    async client, restored."""

    raw: Any
    masker: Masker
    replay: ReplayCache | None = None

    async def __aenter__(self) -> AsyncVeilEventStream:
        if hasattr(self.raw, "__aenter__"):
            await self.raw.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> Any:
        if hasattr(self.raw, "__aexit__"):
            return await self.raw.__aexit__(*exc_info)
        return None

    async def __aiter__(self) -> AsyncIterator[Any]:
        events = EventRestorer(self.masker, self.replay)
        async for event in self.raw:
            for restored in events.feed(event):
                yield restored
        for restored in events.finish():
            yield restored


@dataclass
class AsyncVeilMessageStream(_Delegating):
    """Wraps the SDK's ``AsyncMessageStream`` (``async with client.messages.stream(...)``)."""

    raw: Any
    masker: Masker
    replay: ReplayCache | None = None
    _restorer: Restorer = field(init=False)
    _entered: Any = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._restorer = Restorer(self.masker.vault)

    def _target(self) -> Any:
        return self._entered if self._entered is not None else self.raw

    async def __aenter__(self) -> AsyncVeilMessageStream:
        self._entered = await self.raw.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> Any:
        return await self.raw.__aexit__(*exc_info)

    @property
    def text_stream(self) -> AsyncIterator[str]:
        async def restored_text() -> AsyncIterator[str]:
            async for text in self._target().text_stream:
                restored = self._restorer.feed(text)
                if restored:
                    yield restored
            tail = self._restorer.flush()
            if tail:
                yield tail

        return restored_text()

    async def __aiter__(self) -> AsyncIterator[Any]:
        events = EventRestorer(self.masker, self.replay)
        async for event in self._target():
            for restored in events.feed(event):
                yield restored
        for restored in events.finish():
            yield restored

    async def get_final_message(self) -> Any:
        message = await self._target().get_final_message()
        return restore_message(message, self.masker, self.replay)

    async def get_final_text(self) -> str:
        return self.masker.restore(await self._target().get_final_text())

    @property
    def current_message_snapshot(self) -> Any:
        return restore_message(self._target().current_message_snapshot, self.masker)


def _is_async_client(client: Any) -> bool:
    """True for a client whose ``messages.create`` has to be awaited."""
    return needs_await(getattr(getattr(client, "messages", None), "create", None))


def _masked_call(
    masker: Masker, replay: ReplayCache, messages: list[Any], system: Any, kwargs: dict[str, Any]
) -> dict[str, Any]:
    call_kwargs: dict[str, Any] = dict(kwargs)
    call_kwargs["messages"] = mask_messages(messages, masker, replay)
    if system is not None:
        call_kwargs["system"] = mask_system(system, masker)
    return call_kwargs


@dataclass
class AnthropicVeil:
    """Mask-and-restore wrapper around an ``anthropic.Anthropic`` client.

    Example::

        from anthropic import Anthropic
        from veil.integrations.anthropic import AnthropicVeil

        veil_client = AnthropicVeil(Anthropic())
        response = veil_client.create(
            model="claude-opus-5-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Email alice@example.com"}],
        )
        # response.content[0].text has the real address restored, but the
        # model itself only ever saw a surrogate.
    """

    client: Any
    masker: Masker = field(default_factory=Masker)
    replay: ReplayCache = field(default_factory=ReplayCache)

    def __post_init__(self) -> None:
        if _is_async_client(self.client):
            raise TypeError(
                "AnthropicVeil wraps a synchronous client (anthropic.Anthropic); "
                "use AsyncAnthropicVeil for anthropic.AsyncAnthropic"
            )

    def create(self, *, messages: list[Any], system: Any = None, **kwargs: Any) -> Any:
        """``client.messages.create``: a restored message, or with ``stream=True`` a
        :class:`VeilEventStream` of restored events."""
        call_kwargs = _masked_call(self.masker, self.replay, messages, system, kwargs)
        response = self.client.messages.create(**call_kwargs)
        if call_kwargs.get("stream"):
            return VeilEventStream(response, self.masker, self.replay)
        return restore_message(response, self.masker, self.replay)

    def stream(
        self, *, messages: list[Any], system: Any = None, **kwargs: Any
    ) -> VeilMessageStream:
        call_kwargs = _masked_call(self.masker, self.replay, messages, system, kwargs)
        raw_stream = self.client.messages.stream(**call_kwargs)
        return VeilMessageStream(raw_stream, self.masker, self.replay)


@dataclass
class AsyncAnthropicVeil:
    """Mask-and-restore wrapper around an ``anthropic.AsyncAnthropic`` client.

    Example::

        from anthropic import AsyncAnthropic
        from veil.integrations.anthropic import AsyncAnthropicVeil

        veil_client = AsyncAnthropicVeil(AsyncAnthropic())
        response = await veil_client.create(model=..., max_tokens=1024, messages=[...])

        async with veil_client.stream(model=..., max_tokens=1024, messages=[...]) as stream:
            async for text in stream.text_stream:
                print(text, end="")
    """

    client: Any
    masker: Masker = field(default_factory=Masker)
    replay: ReplayCache = field(default_factory=ReplayCache)

    def __post_init__(self) -> None:
        if not _is_async_client(self.client):
            raise TypeError(
                "AsyncAnthropicVeil wraps an asynchronous client (anthropic.AsyncAnthropic); "
                "use AnthropicVeil for anthropic.Anthropic"
            )

    async def create(self, *, messages: list[Any], system: Any = None, **kwargs: Any) -> Any:
        """``await client.messages.create``: a restored message, or with ``stream=True``
        an :class:`AsyncVeilEventStream` of restored events."""
        call_kwargs = _masked_call(self.masker, self.replay, messages, system, kwargs)
        response = await self.client.messages.create(**call_kwargs)
        if call_kwargs.get("stream"):
            return AsyncVeilEventStream(response, self.masker, self.replay)
        return restore_message(response, self.masker, self.replay)

    def stream(
        self, *, messages: list[Any], system: Any = None, **kwargs: Any
    ) -> AsyncVeilMessageStream:
        call_kwargs = _masked_call(self.masker, self.replay, messages, system, kwargs)
        raw_stream = self.client.messages.stream(**call_kwargs)
        return AsyncVeilMessageStream(raw_stream, self.masker, self.replay)
