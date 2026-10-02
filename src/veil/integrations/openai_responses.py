"""Masking and restoring for the OpenAI **Responses API**
(``client.responses.create``), used by :class:`veil.integrations.openai.OpenAIVeil`'s
``create_response`` / ``stream_response``.

Built against the shapes in the ``openai`` Python SDK's ``openai.types.responses``:

**What gets masked:** ``instructions``, and in ``input`` (a string or a list of
items) every message's text (a string, or ``input_text`` / ``output_text``
parts), ``function_call`` arguments (a JSON *string*, as in Chat Completions),
``function_call_output`` output, and the input and output of custom tool calls.
Images and files pass through, as do items veil doesn't recognize. A reasoning
item's summary text is masked (veil restores it on the way in), but its
encrypted content never changes.

**What gets restored:** in ``output``, message text and refusals,
``function_call`` arguments, custom tool call input and reasoning summaries.
``Response.output_text`` is computed from ``output`` by the SDK, so it comes back
restored too.

**Streaming:** ``response.output_text.delta`` and ``response.refusal.delta``
text, and ``response.function_call_arguments.delta`` fragments, go through a
:class:`veil.restore.Restorer` per content part or call, so a surrogate split
across events is still caught. Text held back because it might begin a
surrogate is released before the matching ``.done`` event, as one more delta
event: a copy of the last delta event of that part or call (same SDK type,
ids and sequence number) carrying the held-back text. ``.done`` events,
finished items and parts, and the final response are restored whole.

**History:** with ``previous_response_id`` or a ``conversation``, the server
keeps the masked history and nothing is resent. A stateless application that
feeds ``output`` items back into ``input`` gets each item veil restored replaced
by the exact item the model produced (see
:class:`veil.integrations._common.ReplayCache`), so real values never return
to the API and reasoning items stay valid. Either way the same ``Masker`` (and
so the same vault) has to serve every turn of a conversation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

from veil.integrations._common import ReplayCache, get_field, model_copy_with, restore_arguments
from veil.masker import Masker
from veil.restore import Restorer

#: Message content parts whose ``text`` is masked on the way out.
_TEXT_PARTS = ("input_text", "output_text", "text")


def _mask_parts(parts: list[Any], masker: Masker) -> list[Any]:
    out = []
    for part in parts:
        part_type = get_field(part, "type")
        text = get_field(part, "text")
        refusal = get_field(part, "refusal")
        if part_type in _TEXT_PARTS and isinstance(text, str):
            part = model_copy_with(part, text=masker.mask(text))
        elif part_type == "refusal" and isinstance(refusal, str):
            part = model_copy_with(part, refusal=masker.mask(refusal))
        out.append(part)
    return out


def _mask_text_or_parts(value: Any, masker: Masker) -> Any:
    if isinstance(value, str):
        return masker.mask(value)
    if isinstance(value, list):
        return _mask_parts(value, masker)
    return value


def _mask_item(item: Any, masker: Masker) -> Any:
    item_type = get_field(item, "type")
    # An "easy" input message has a role and content but no type.
    if item_type == "message" or (item_type is None and get_field(item, "role") is not None):
        content = get_field(item, "content")
        return model_copy_with(item, content=_mask_text_or_parts(content, masker))
    if item_type == "function_call":
        arguments = get_field(item, "arguments")
        if isinstance(arguments, str):
            return model_copy_with(item, arguments=masker.mask(arguments))
    elif item_type in ("function_call_output", "custom_tool_call_output"):
        return model_copy_with(item, output=_mask_text_or_parts(get_field(item, "output"), masker))
    elif item_type == "custom_tool_call":
        tool_input = get_field(item, "input")
        if isinstance(tool_input, str):
            return model_copy_with(item, input=masker.mask(tool_input))
    elif item_type == "reasoning":
        # veil restores reasoning summaries, so one resent without a replay hit (after a
        # restart, say) may hold real values. Only the summary text changes; the
        # encrypted content is never touched.
        summary = get_field(item, "summary")
        if isinstance(summary, list) and summary:
            return model_copy_with(item, summary=_map_text(summary, masker.mask))
    return item


def _map_text(entries: list[Any], fn: Any) -> list[Any]:
    return [
        model_copy_with(e, text=fn(get_field(e, "text")))
        if isinstance(get_field(e, "text"), str)
        else e
        for e in entries
    ]


def mask_responses_input(input: Any, masker: Masker, replay: ReplayCache | None = None) -> Any:
    """Mask a Responses API ``input``: a string, or a list of input items.

    With ``replay``, an item veil restored earlier (an ``output`` item fed back
    as history) is replaced by the exact original instead of being re-masked.
    """
    if isinstance(input, str):
        return masker.mask(input)
    if not isinstance(input, list):
        return input
    out = []
    for item in input:
        if replay is not None:
            original = replay.original_for(item)
            if original is not None:
                out.append(original)
                continue
        out.append(_mask_item(item, masker))
    return out


def _restore_part(part: Any, masker: Masker) -> Any:
    part_type = get_field(part, "type")
    if part_type == "output_text" and isinstance(get_field(part, "text"), str):
        return model_copy_with(part, text=masker.restore(get_field(part, "text")))
    if part_type == "refusal" and isinstance(get_field(part, "refusal"), str):
        return model_copy_with(part, refusal=masker.restore(get_field(part, "refusal")))
    return part


def restore_output_item(item: Any, masker: Masker) -> Any:
    """Restore one ``output`` item (message, function or custom tool call, reasoning)."""
    item_type = get_field(item, "type")
    if item_type == "message":
        content = get_field(item, "content")
        if isinstance(content, list):
            return model_copy_with(item, content=[_restore_part(p, masker) for p in content])
    elif item_type == "function_call":
        arguments = get_field(item, "arguments")
        if isinstance(arguments, str):
            return model_copy_with(item, arguments=restore_arguments(arguments, masker))
    elif item_type == "custom_tool_call":
        tool_input = get_field(item, "input")
        if isinstance(tool_input, str):
            return model_copy_with(item, input=masker.restore(tool_input))
    elif item_type == "reasoning":
        summary = get_field(item, "summary")
        if isinstance(summary, list) and summary:
            return model_copy_with(item, summary=_map_text(summary, masker.restore))
    return item


def restore_response(response: Any, masker: Masker, replay: ReplayCache | None = None) -> Any:
    """Restore a full Responses API ``Response``'s ``output`` items.

    With ``replay``, each restored item is remembered against the original, so
    feeding it back as ``input`` resends exactly what the model produced.
    """
    output = get_field(response, "output")
    if not isinstance(output, list):
        return response
    restored = [restore_output_item(item, masker) for item in output]
    if replay is not None:
        for new, old in zip(restored, output, strict=True):
            replay.remember(new, old)
    return model_copy_with(response, output=restored)


#: Event types that carry a whole ``response`` worth remembering for replay.
_FINAL_EVENTS = ("response.completed", "response.incomplete")


@dataclass
class _Pending:
    """A streamed text part or argument string: its restorer, and the last
    delta event seen for it (the template for releasing held-back text)."""

    restorer: Restorer
    last_delta: Any = None

    def feed(self, event: Any, delta: str) -> Any:
        self.last_delta = event
        return model_copy_with(event, delta=self.restorer.feed(delta))

    def release(self) -> Any | None:
        """A copy of the last delta event carrying whatever is still held back, if anything."""
        tail = self.restorer.flush()
        if not tail or self.last_delta is None:
            return None
        return model_copy_with(self.last_delta, delta=tail)


@dataclass
class OpenAIResponsesStream:
    """Wraps the event iterator from ``client.responses.create(..., stream=True)``
    so text, refusals and tool-call arguments arrive restored."""

    raw: Any
    masker: Masker
    replay: ReplayCache | None = None
    _pending: dict[tuple[str, str, int], _Pending] = field(init=False, default_factory=dict)

    def __enter__(self) -> OpenAIResponsesStream:
        if hasattr(self.raw, "__enter__"):
            self.raw.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> Any:
        if hasattr(self.raw, "__exit__"):
            return self.raw.__exit__(*exc_info)
        return None

    def __getattr__(self, name: str) -> Any:
        # close(), response, ...: whatever veil does not wrap is the SDK stream's.
        if name.startswith("_") or name == "raw":
            raise AttributeError(name)
        return getattr(self.raw, name)

    def __iter__(self) -> Iterator[Any]:
        for event in self.raw:
            yield from self._restore_event(event)
        yield from self._release_all()

    def _release_all(self) -> Iterator[Any]:
        """A stream cut off before its .done events: release what's held back."""
        for pending in self._pending.values():
            released = pending.release()
            if released is not None:
                yield released
        self._pending.clear()

    def _key(self, kind: str, event: Any) -> tuple[str, str, int]:
        return (kind, get_field(event, "item_id"), get_field(event, "content_index", 0))

    def _restore_event(self, event: Any) -> Iterator[Any]:
        event_type = get_field(event, "type")
        kind = _STREAMED.get(event_type)
        if kind is not None:
            delta = get_field(event, "delta")
            if isinstance(delta, str):
                key = self._key(kind, event)
                if key not in self._pending:
                    self._pending[key] = _Pending(
                        Restorer(self.masker.vault, json_string=kind == "arguments")
                    )
                event = self._pending[key].feed(event, delta)
        elif event_type in _DONE:
            kind, field_name = _DONE[event_type]
            pending = self._pending.pop(self._key(kind, event), None)
            released = pending.release() if pending is not None else None
            if released is not None:
                yield released
            value = get_field(event, field_name)
            if isinstance(value, str):
                restored = (
                    restore_arguments(value, self.masker)
                    if kind == "arguments"
                    else self.masker.restore(value)
                )
                event = model_copy_with(event, **{field_name: restored})
        elif event_type in ("response.output_item.added", "response.output_item.done"):
            item = get_field(event, "item")
            if item is not None:
                event = model_copy_with(event, item=restore_output_item(item, self.masker))
        elif event_type in ("response.content_part.added", "response.content_part.done"):
            part = get_field(event, "part")
            if part is not None:
                event = model_copy_with(event, part=_restore_part(part, self.masker))
        elif get_field(event, "response") is not None:
            # response.created / in_progress / completed / incomplete / failed
            replay = self.replay if event_type in _FINAL_EVENTS else None
            event = model_copy_with(
                event, response=restore_response(get_field(event, "response"), self.masker, replay)
            )
        yield event


#: Delta events restored through a streaming Restorer, by the kind of string they build.
_STREAMED = {
    "response.output_text.delta": "output_text",
    "response.refusal.delta": "refusal",
    "response.function_call_arguments.delta": "arguments",
}

#: The matching .done events: the kind, and the field holding the whole string.
_DONE = {
    "response.output_text.done": ("output_text", "text"),
    "response.refusal.done": ("refusal", "refusal"),
    "response.function_call_arguments.done": ("arguments", "arguments"),
}


class AsyncOpenAIResponsesStream(OpenAIResponsesStream):
    """The same for ``await client.responses.create(..., stream=True)`` on an
    ``AsyncOpenAI`` client: ``async for event in stream``."""

    async def __aenter__(self) -> AsyncOpenAIResponsesStream:
        if hasattr(self.raw, "__aenter__"):
            await self.raw.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> Any:
        if hasattr(self.raw, "__aexit__"):
            return await self.raw.__aexit__(*exc_info)
        return None

    async def __aiter__(self) -> AsyncIterator[Any]:
        async for event in self.raw:
            for restored in self._restore_event(event):
                yield restored
        for restored in self._release_all():
            yield restored

    def __iter__(self) -> Iterator[Any]:
        raise TypeError("this is an async stream: use `async for`")
