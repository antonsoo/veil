"""A thin wrapper around the OpenAI Python SDK that masks outgoing messages
and restores PII in the response, streaming included.

Requires the ``openai`` extra (``pip install "veil-pii[openai] @ git+https://github.com/antonsoo/veil"``). Built
against the documented shape of ``client.chat.completions.create(...,
stream=True)`` — a message list of role/content dicts, and a stream of
``ChatCompletionChunk``-shaped objects with ``choices[].delta.content`` and
``choices[].delta.tool_calls[].function.arguments`` (a fragment of a JSON
*string*, unlike Anthropic's already-structured ``tool_use.input``). This
module makes no live API calls; see ``tests/test_integration_openai.py``
for the fakes it's tested against.

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

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from veil.integrations._common import ReplayCache, get_field, model_copy_with, restore_value
from veil.masker import Masker
from veil.restore import Restorer, restore_json_text


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


def restore_arguments(arguments: str, masker: Masker) -> str:
    """Restore a complete tool-call ``arguments`` JSON string."""
    try:
        parsed = json.loads(arguments)
    except ValueError:
        return restore_json_text(arguments, masker.vault)  # truncated or not JSON: best effort
    restored = restore_value(parsed, masker)
    return arguments if restored == parsed else json.dumps(restored, ensure_ascii=False)


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
class OpenAIVeilStream:
    """Wraps the raw chunk iterator from ``client.chat.completions.create(
    ..., stream=True)`` so text and tool-call arguments arrive restored.
    """

    raw: Iterator[Any]
    masker: Masker
    _content_restorer: Restorer = field(init=False)
    _tool_restorers: dict[int, Restorer] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._content_restorer = Restorer(self.masker.vault)

    def __iter__(self) -> Iterator[Any]:
        for chunk in self.raw:
            yield self._restore_chunk(chunk)
        yield from self._flush_trailing()

    def _restore_chunk(self, chunk: Any) -> Any:
        choices = get_field(chunk, "choices") or []
        new_choices = [self._restore_choice_delta(c) for c in choices]
        return model_copy_with(chunk, choices=new_choices) if choices else chunk

    def _restore_choice_delta(self, choice: Any) -> Any:
        delta = get_field(choice, "delta")
        if delta is None:
            return choice
        updates: dict[str, Any] = {}
        content = get_field(delta, "content")
        if isinstance(content, str):
            updates["content"] = self._content_restorer.feed(content)
        tool_calls = get_field(delta, "tool_calls")
        if tool_calls:
            updates["tool_calls"] = [self._restore_tool_call_delta(c) for c in tool_calls]
        if not updates:
            return choice
        return model_copy_with(choice, delta=model_copy_with(delta, **updates))

    def _restore_tool_call_delta(self, call: Any) -> Any:
        fn = get_field(call, "function")
        if fn is None:
            return call
        args = get_field(fn, "arguments")
        if not isinstance(args, str):
            return call
        index = get_field(call, "index", 0)
        restorer = self._tool_restorers.setdefault(
            index, Restorer(self.masker.vault, json_string=True)
        )
        return model_copy_with(call, function=model_copy_with(fn, arguments=restorer.feed(args)))

    def _flush_trailing(self) -> Iterator[Any]:
        """After the real stream ends, emit any text still held back
        because it could have been (but wasn't) the start of a surrogate.
        Synthesized as plain dict chunks, since we can't construct a real
        SDK response object without its private constructor.
        """
        tail = self._content_restorer.flush()
        if tail:
            yield {"choices": [{"index": 0, "delta": {"content": tail}}]}
        for index, restorer in self._tool_restorers.items():
            tail = restorer.flush()
            if tail:
                yield {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [{"index": index, "function": {"arguments": tail}}]
                            },
                        }
                    ]
                }


@dataclass
class OpenAIVeil:
    """Mask-and-restore wrapper around an ``openai.OpenAI`` client.

    Example::

        from openai import OpenAI
        from veil.integrations.openai import OpenAIVeil

        veil_client = OpenAIVeil(OpenAI())
        response = veil_client.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Email alice@example.com"}],
        )
    """

    client: Any
    masker: Masker = field(default_factory=Masker)
    replay: ReplayCache = field(default_factory=ReplayCache)

    def create(self, *, messages: list[Any], **kwargs: Any) -> Any:
        masked = mask_messages(messages, self.masker, self.replay)
        response = self.client.chat.completions.create(messages=masked, **kwargs)
        return restore_response(response, self.masker, self.replay)

    def stream(self, *, messages: list[Any], **kwargs: Any) -> OpenAIVeilStream:
        masked = mask_messages(messages, self.masker, self.replay)
        raw = self.client.chat.completions.create(messages=masked, stream=True, **kwargs)
        return OpenAIVeilStream(raw, self.masker)
