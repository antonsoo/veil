"""A thin wrapper around the OpenAI Python SDK that masks outgoing messages
and restores PII in the response, streaming included.

Requires the ``openai`` extra (``pip install "veil-pii[openai]"``). Built
against the documented shape of ``client.chat.completions.create(...,
stream=True)`` — a message list of role/content dicts, and a stream of
``ChatCompletionChunk``-shaped objects with ``choices[].delta.content`` and
``choices[].delta.tool_calls[].function.arguments`` (a fragment of a JSON
*string*, unlike Anthropic's already-structured ``tool_use.input``). This
module makes no live API calls. ``tests/test_integration_openai.py`` tests it
against fakes; ``tests/test_sdk_openai.py`` runs the real SDK, sync and async,
over a mocked HTTP transport that answers in the API's wire format.

**Streaming.** ``OpenAIVeil.stream(...)`` and ``create(..., stream=True)`` both
return an :class:`OpenAIVeilStream`. Each choice has its own restorers (for
its content, its refusal, and each of its tool calls), since ``n > 1`` choices
arrive interleaved. Text held back because it might begin a surrogate is
released in the chunk that carries the choice's ``finish_reason``, so nothing
arrives after a choice has finished.

**Async.** :class:`AsyncOpenAIVeil` is the same wrapper for
``openai.AsyncOpenAI``; each refuses the other kind of client.

**Tool-call arguments are a JSON string.** In a complete response they are
parsed, restored value by value, and re-serialized, so the restore doesn't
depend on how the model escaped the surrogate (a model may write ``⟨`` as
``\\u27e8``). Mid-stream a surrogate can straddle a ``{``/``"``/``,``
boundary, so the fragments go through a :class:`veil.restore.Restorer` in
JSON-string mode instead - one per tool-call index, since parallel tool
calls interleave their fragments by index - which also recognizes the
escaped form and writes originals JSON-escaped.

**History replay:** an assistant message veil restored is swapped back for
the exact message the model produced when the application resends it, so
real values never return to the API and the resent history stays
byte-identical (see :class:`veil.integrations._common.ReplayCache`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

from veil.integrations import openai_responses
from veil.integrations._common import (
    ReplayCache,
    get_field,
    model_copy_with,
    needs_await,
    restore_arguments,
)
from veil.masker import Masker
from veil.restore import Restorer

__all__ = [
    "AsyncOpenAIVeil",
    "AsyncOpenAIVeilStream",
    "ChunkRestorer",
    "OpenAIVeil",
    "OpenAIVeilStream",
    "mask_content",
    "mask_messages",
    "restore_arguments",
    "restore_response",
]


def mask_content(content: Any, masker: Masker) -> Any:
    if isinstance(content, str):
        return masker.mask(content)
    if isinstance(content, list):
        return [_mask_content_block(b, masker) for b in content]
    return content


def _mask_content_block(block: Any, masker: Masker) -> Any:
    if get_field(block, "type") == "text":
        text = get_field(block, "text")
        if isinstance(text, str):
            return model_copy_with(block, text=masker.mask(text))
    return block


def _mask_tool_calls(tool_calls: Any, masker: Masker) -> Any:
    if not tool_calls:
        return tool_calls
    out = []
    for call in tool_calls:
        fn = get_field(call, "function")
        if fn is not None:
            args = get_field(fn, "arguments")
            if isinstance(args, str):
                fn = model_copy_with(fn, arguments=masker.mask(args))
            call = model_copy_with(call, function=fn)
        out.append(call)
    return out


def mask_messages(
    messages: list[Any], masker: Masker, replay: ReplayCache | None = None
) -> list[Any]:
    """Mask ``content`` on every message (system/user/assistant/tool), and
    ``tool_calls[].function.arguments`` on any prior assistant turns being
    resent as history — those may contain real values a previous
    :meth:`veil.masker.Masker.restore` call put back; re-masking maps them
    to the *same* surrogate already in the vault rather than a new one.
    With ``replay``, a message veil restored is replaced by the original.
    """
    out = []
    for message in messages:
        if replay is not None and get_field(message, "role") == "assistant":
            original = replay.original_for(message)
            if original is not None:
                out.append(original)
                continue
        content = get_field(message, "content")
        updates: dict[str, Any] = {}
        if content is not None:
            updates["content"] = mask_content(content, masker)
        tool_calls = get_field(message, "tool_calls")
        if tool_calls:
            updates["tool_calls"] = _mask_tool_calls(tool_calls, masker)
        out.append(model_copy_with(message, **updates) if updates else message)
    return out


def restore_response(response: Any, masker: Masker, replay: ReplayCache | None = None) -> Any:
    """Restore a full (non-streamed) ``ChatCompletion`` response."""
    choices = get_field(response, "choices") or []
    return model_copy_with(response, choices=[_restore_choice(c, masker, replay) for c in choices])


def _restore_choice(choice: Any, masker: Masker, replay: ReplayCache | None = None) -> Any:
    message = get_field(choice, "message")
    if message is None:
        return choice
    updates: dict[str, Any] = {}
    content = get_field(message, "content")
    if isinstance(content, str):
        updates["content"] = masker.restore(content)
    tool_calls = get_field(message, "tool_calls")
    if tool_calls:
        new_calls = []
        for call in tool_calls:
            fn = get_field(call, "function")
            if fn is not None:
                args = get_field(fn, "arguments")
                if isinstance(args, str):
                    fn = model_copy_with(fn, arguments=restore_arguments(args, masker))
                call = model_copy_with(call, function=fn)
            new_calls.append(call)
        updates["tool_calls"] = new_calls
    if not updates:
        return choice
    restored = model_copy_with(message, **updates)
    if replay is not None:
        replay.remember(restored, message)
    return model_copy_with(choice, message=restored)


@dataclass
class _Held:
    """One streamed string (a choice's content or refusal, a tool call's arguments): its
    restorer, and the chunk and choice (and tool-call delta) that last carried it, which are
    the template for releasing held-back text if the stream is cut off."""

    restorer: Restorer
    chunk: Any = None
    choice: Any = None
    call: Any = None


class ChunkRestorer:
    """Restores the chunks of one Chat Completions stream, one at a time. No I/O: the sync
    and the async stream wrappers both drive it."""

    def __init__(self, masker: Masker) -> None:
        self._masker = masker
        # Keyed by choice index: n > 1 choices arrive interleaved, and text fed to one
        # restorer from two of them would be stitched together across choices.
        self._text: dict[tuple[str, int], _Held] = {}
        self._tools: dict[tuple[int, int], _Held] = {}

    def _held_text(self, kind: str, index: int) -> _Held:
        key = (kind, index)
        if key not in self._text:
            self._text[key] = _Held(Restorer(self._masker.vault))
        return self._text[key]

    def feed(self, chunk: Any) -> list[Any]:
        choices = get_field(chunk, "choices") or []
        if not choices:
            return [chunk]  # e.g. the usage-only chunk of stream_options.include_usage
        restored = [self._restore_choice(chunk, choice) for choice in choices]
        return [model_copy_with(chunk, choices=restored)]

    def _restore_choice(self, chunk: Any, choice: Any) -> Any:
        delta = get_field(choice, "delta")
        if delta is None:
            return choice
        index = get_field(choice, "index", 0)
        finished = get_field(choice, "finish_reason") is not None
        updates: dict[str, Any] = {}
        for kind in ("content", "refusal"):
            value = get_field(delta, kind)
            piece = ""
            if isinstance(value, str):
                held = self._held_text(kind, index)
                held.chunk, held.choice = chunk, choice
                piece = held.restorer.feed(value)
                updates[kind] = piece
            if finished and (kind, index) in self._text:
                # The choice is done: what was held back for it belongs in this chunk.
                tail = self._text.pop((kind, index)).restorer.flush()
                if tail:
                    updates[kind] = piece + tail
        tool_calls = get_field(delta, "tool_calls")
        calls = [self._restore_tool_call(chunk, choice, index, c) for c in tool_calls or []]
        if finished:
            calls.extend(self._release_tools(index))
        if calls:
            updates["tool_calls"] = calls
        if not updates:
            return choice
        return model_copy_with(choice, delta=model_copy_with(delta, **updates))

    def _restore_tool_call(self, chunk: Any, choice: Any, index: int, call: Any) -> Any:
        fn = get_field(call, "function")
        if fn is None:
            return call
        args = get_field(fn, "arguments")
        if not isinstance(args, str):
            return call
        key = (index, get_field(call, "index", 0))
        if key not in self._tools:
            self._tools[key] = _Held(Restorer(self._masker.vault, json_string=True))
        held = self._tools[key]
        held.chunk, held.choice, held.call = chunk, choice, call
        return model_copy_with(
            call, function=model_copy_with(fn, arguments=held.restorer.feed(args))
        )

    def _release_tools(self, index: int) -> list[Any]:
        """Tool-call deltas carrying what is still held back for a choice's tool calls."""
        out = []
        for key in [k for k in self._tools if k[0] == index]:
            held = self._tools.pop(key)
            tail = held.restorer.flush()
            if tail and held.call is not None:
                fn = model_copy_with(get_field(held.call, "function"), arguments=tail)
                out.append(model_copy_with(held.call, function=fn))
        return out

    def finish(self) -> list[Any]:
        """After the stream ends: chunks for text still held back for choices that never
        got a ``finish_reason`` (a stream cut off). Each is a copy of the last chunk that
        carried that string (same SDK type, so ``chunk.choices[0].delta`` keeps working),
        holding only that choice and only the held-back text."""
        out = []
        for (kind, _), held in list(self._text.items()):
            tail = held.restorer.flush()
            if tail and held.chunk is not None:
                other = "refusal" if kind == "content" else "content"
                updates = {kind: tail, other: None, "tool_calls": None}
                out.append(_with_delta(held.chunk, held.choice, **updates))
        self._text.clear()
        for held in list(self._tools.values()):
            tail = held.restorer.flush()
            if tail and held.call is not None:
                fn = model_copy_with(get_field(held.call, "function"), arguments=tail)
                call = model_copy_with(held.call, function=fn)
                out.append(_with_delta(held.chunk, held.choice, content=None, tool_calls=[call]))
        self._tools.clear()
        return out


def _with_delta(chunk: Any, choice: Any, **delta_updates: Any) -> Any:
    """``chunk`` holding only ``choice``, its delta replaced by ``delta_updates``."""
    delta = get_field(choice, "delta")
    if not isinstance(delta, dict) and not hasattr(delta, "refusal"):
        delta_updates.pop("refusal", None)  # a test double without the field: don't add it
    delta = model_copy_with(delta, **delta_updates)
    return model_copy_with(chunk, choices=[model_copy_with(choice, delta=delta)])


class _Delegating:
    """Hands anything veil does not wrap (``close()``, ``response``, ...) to the SDK's
    stream underneath."""

    raw: Any

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name == "raw":
            raise AttributeError(name)
        return getattr(self.raw, name)


@dataclass
class OpenAIVeilStream(_Delegating):
    """Wraps the raw chunk iterator from ``client.chat.completions.create(
    ..., stream=True)`` so text and tool-call arguments arrive restored.
    """

    raw: Any
    masker: Masker

    def __enter__(self) -> OpenAIVeilStream:
        if hasattr(self.raw, "__enter__"):
            self.raw.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> Any:
        if hasattr(self.raw, "__exit__"):
            return self.raw.__exit__(*exc_info)
        return None

    def __iter__(self) -> Iterator[Any]:
        chunks = ChunkRestorer(self.masker)
        for chunk in self.raw:
            yield from chunks.feed(chunk)
        yield from chunks.finish()


@dataclass
class AsyncOpenAIVeilStream(_Delegating):
    """The same for ``await client.chat.completions.create(..., stream=True)`` on an
    ``AsyncOpenAI`` client."""

    raw: Any
    masker: Masker

    async def __aenter__(self) -> AsyncOpenAIVeilStream:
        if hasattr(self.raw, "__aenter__"):
            await self.raw.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> Any:
        if hasattr(self.raw, "__aexit__"):
            return await self.raw.__aexit__(*exc_info)
        return None

    async def __aiter__(self) -> AsyncIterator[Any]:
        chunks = ChunkRestorer(self.masker)
        async for chunk in self.raw:
            for restored in chunks.feed(chunk):
                yield restored
        for restored in chunks.finish():
            yield restored


def _is_async_client(client: Any) -> bool:
    """True for a client whose ``chat.completions.create`` has to be awaited."""
    completions = getattr(getattr(client, "chat", None), "completions", None)
    return needs_await(getattr(completions, "create", None))


def _response_kwargs(
    masker: Masker, replay: ReplayCache, input: Any, instructions: Any, kwargs: dict[str, Any]
) -> dict[str, Any]:
    call_kwargs = dict(kwargs)
    call_kwargs["input"] = openai_responses.mask_responses_input(input, masker, replay)
    if isinstance(instructions, str):
        call_kwargs["instructions"] = masker.mask(instructions)
    elif instructions is not None:
        call_kwargs["instructions"] = instructions
    return call_kwargs


@dataclass
class OpenAIVeil:
    """Mask-and-restore wrapper around an ``openai.OpenAI`` client.

    Example::

        from openai import OpenAI
        from veil.integrations.openai import OpenAIVeil

        veil_client = OpenAIVeil(OpenAI())
        response = veil_client.create(  # Chat Completions
            model="gpt-6-sol",
            messages=[{"role": "user", "content": "Email alice@example.com"}],
        )
        response = veil_client.create_response(  # Responses API
            model="gpt-6-sol",
            input="Email alice@example.com",
        )
    """

    client: Any
    masker: Masker = field(default_factory=Masker)
    replay: ReplayCache = field(default_factory=ReplayCache)

    def __post_init__(self) -> None:
        if _is_async_client(self.client):
            raise TypeError(
                "OpenAIVeil wraps a synchronous client (openai.OpenAI); "
                "use AsyncOpenAIVeil for openai.AsyncOpenAI"
            )

    def create(self, *, messages: list[Any], **kwargs: Any) -> Any:
        """``client.chat.completions.create``: a restored completion, or with
        ``stream=True`` an :class:`OpenAIVeilStream` of restored chunks."""
        masked = mask_messages(messages, self.masker, self.replay)
        response = self.client.chat.completions.create(messages=masked, **kwargs)
        if kwargs.get("stream"):
            return OpenAIVeilStream(response, self.masker)
        return restore_response(response, self.masker, self.replay)

    def stream(self, *, messages: list[Any], **kwargs: Any) -> OpenAIVeilStream:
        kwargs.pop("stream", None)
        masked = mask_messages(messages, self.masker, self.replay)
        raw = self.client.chat.completions.create(messages=masked, stream=True, **kwargs)
        return OpenAIVeilStream(raw, self.masker)

    def create_response(self, *, input: Any, instructions: Any = None, **kwargs: Any) -> Any:
        """``client.responses.create`` with ``input`` and ``instructions`` masked
        and the response's ``output`` restored (see :mod:`veil.integrations.openai_responses`).
        With ``stream=True``, an :class:`~veil.integrations.openai_responses.OpenAIResponsesStream`."""
        call_kwargs = _response_kwargs(self.masker, self.replay, input, instructions, kwargs)
        response = self.client.responses.create(**call_kwargs)
        if call_kwargs.get("stream"):
            return openai_responses.OpenAIResponsesStream(response, self.masker, self.replay)
        return openai_responses.restore_response(response, self.masker, self.replay)

    def stream_response(
        self, *, input: Any, instructions: Any = None, **kwargs: Any
    ) -> openai_responses.OpenAIResponsesStream:
        """``client.responses.create(..., stream=True)``, yielding restored events."""
        kwargs.pop("stream", None)
        call_kwargs = _response_kwargs(self.masker, self.replay, input, instructions, kwargs)
        raw = self.client.responses.create(stream=True, **call_kwargs)
        return openai_responses.OpenAIResponsesStream(raw, self.masker, self.replay)


@dataclass
class AsyncOpenAIVeil:
    """Mask-and-restore wrapper around an ``openai.AsyncOpenAI`` client.

    Example::

        from openai import AsyncOpenAI
        from veil.integrations.openai import AsyncOpenAIVeil

        veil_client = AsyncOpenAIVeil(AsyncOpenAI())
        response = await veil_client.create(model=..., messages=[...])
        async for chunk in await veil_client.stream(model=..., messages=[...]):
            print(chunk.choices[0].delta.content or "", end="")
    """

    client: Any
    masker: Masker = field(default_factory=Masker)
    replay: ReplayCache = field(default_factory=ReplayCache)

    def __post_init__(self) -> None:
        if not _is_async_client(self.client):
            raise TypeError(
                "AsyncOpenAIVeil wraps an asynchronous client (openai.AsyncOpenAI); "
                "use OpenAIVeil for openai.OpenAI"
            )

    async def create(self, *, messages: list[Any], **kwargs: Any) -> Any:
        masked = mask_messages(messages, self.masker, self.replay)
        response = await self.client.chat.completions.create(messages=masked, **kwargs)
        if kwargs.get("stream"):
            return AsyncOpenAIVeilStream(response, self.masker)
        return restore_response(response, self.masker, self.replay)

    async def stream(self, *, messages: list[Any], **kwargs: Any) -> AsyncOpenAIVeilStream:
        kwargs.pop("stream", None)
        masked = mask_messages(messages, self.masker, self.replay)
        raw = await self.client.chat.completions.create(messages=masked, stream=True, **kwargs)
        return AsyncOpenAIVeilStream(raw, self.masker)

    async def create_response(self, *, input: Any, instructions: Any = None, **kwargs: Any) -> Any:
        call_kwargs = _response_kwargs(self.masker, self.replay, input, instructions, kwargs)
        response = await self.client.responses.create(**call_kwargs)
        if call_kwargs.get("stream"):
            return openai_responses.AsyncOpenAIResponsesStream(response, self.masker, self.replay)
        return openai_responses.restore_response(response, self.masker, self.replay)

    async def stream_response(
        self, *, input: Any, instructions: Any = None, **kwargs: Any
    ) -> openai_responses.AsyncOpenAIResponsesStream:
        kwargs.pop("stream", None)
        call_kwargs = _response_kwargs(self.masker, self.replay, input, instructions, kwargs)
        raw = await self.client.responses.create(stream=True, **call_kwargs)
        return openai_responses.AsyncOpenAIResponsesStream(raw, self.masker, self.replay)
