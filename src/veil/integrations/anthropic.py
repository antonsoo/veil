"""A thin wrapper around the Anthropic Python SDK that masks outgoing
messages and restores PII in the response, streaming included.

Requires the ``anthropic`` extra (``pip install "veil-pii[anthropic]"``).
This module only touches the SDK's public, documented surface
(``client.messages.create`` / ``client.messages.stream``, the
``MessageStream`` helper's ``text_stream`` / ``get_final_message()``) so it
works against the real SDK or against a test double shaped like it — see
``tests/test_integration_anthropic.py``, which uses fakes throughout since
this repo has no API key and makes no live calls.

**What gets masked:** every text block and tool-result content string in
``messages``, and every text block in ``system`` (both the plain-string and
the list-of-blocks forms). Images and other binary content pass through
untouched — veil only understands text.

**What gets restored:** every text block and tool_use ``input`` value in
the response, including from a token stream (via
:class:`veil.restore.Restorer`, so a surrogate split across chunks is still
caught).
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from typing import Any

from veil.integrations._common import get_field, model_copy_with, restore_value
from veil.masker import Masker
from veil.restore import Restorer


def mask_content(content: Any, masker: Masker) -> Any:
    """Mask a message's ``content`` field (a string, or a list of blocks)."""
    if isinstance(content, str):
        return masker.mask(content)
    if isinstance(content, list):
        return [_mask_block(b, masker) for b in content]
    return content


def _mask_block(block: Any, masker: Masker) -> Any:
    block_type = get_field(block, "type")
    if block_type == "text":
        text = get_field(block, "text")
        if isinstance(text, str):
            return model_copy_with(block, text=masker.mask(text))
    elif block_type == "tool_result":
        result_content = get_field(block, "content")
        if result_content is not None:
            return model_copy_with(block, content=mask_content(result_content, masker))
    return block


def mask_messages(messages: list[Any], masker: Masker) -> list[Any]:
    return [
        model_copy_with(m, content=mask_content(get_field(m, "content"), masker)) for m in messages
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


def restore_message(message: Any, masker: Masker) -> Any:
    """Restore a full (non-streamed) response message's content blocks."""
    content = get_field(message, "content")
    if not isinstance(content, list):
        return message
    return model_copy_with(message, content=[_restore_block(b, masker) for b in content])


@dataclass
class VeilMessageStream:
    """Wraps the Anthropic SDK's ``MessageStream`` (the object returned by
    ``client.messages.stream(...)``) so text arrives already restored.
    """

    raw: Any  # the object returned by client.messages.stream(...) (a context manager)
    masker: Masker
    _restorer: Restorer = field(init=False)
    _entered: Any = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._restorer = Restorer(self.masker.vault)

    def __enter__(self) -> VeilMessageStream:
        self._entered = self.raw.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> Any:
        return self.raw.__exit__(*exc_info)

    @property
    def text_stream(self) -> Generator[str, None, None]:
        stream = self._entered if self._entered is not None else self.raw
        for text in stream.text_stream:
            restored = self._restorer.feed(text)
            if restored:
                yield restored
        tail = self._restorer.flush()
        if tail:
            yield tail

    def __iter__(self) -> Iterator[Any]:
        """Yield raw SDK events, with text deltas restored in place.

        Tool-input JSON deltas (``input_json_delta`` / ``partial_json``) are
        passed through unrestored: they're accumulated fragments of a JSON
        string, not natural-language text, and are fully restored once
        assembled in :meth:`get_final_message`.
        """
        stream = self._entered if self._entered is not None else self.raw
        for event in stream:
            if get_field(event, "type") == "content_block_delta":
                delta = get_field(event, "delta")
                if get_field(delta, "type") == "text_delta":
                    text = get_field(delta, "text", "")
                    restored = self._restorer.feed(text)
                    event = model_copy_with(event, delta=model_copy_with(delta, text=restored))
            yield event

    def get_final_message(self) -> Any:
        stream = self._entered if self._entered is not None else self.raw
        message = stream.get_final_message()
        return restore_message(message, self.masker)


@dataclass
class AnthropicVeil:
    """Mask-and-restore wrapper around an ``anthropic.Anthropic`` client.

    Example::

        from anthropic import Anthropic
        from veil.integrations.anthropic import AnthropicVeil

        veil_client = AnthropicVeil(Anthropic())
        response = veil_client.create(
            model="claude-opus-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Email alice@example.com"}],
        )
        # response.content[0].text has the real address restored, but the
        # model itself only ever saw a surrogate.
    """

    client: Any
    masker: Masker = field(default_factory=Masker)

    def create(self, *, messages: list[Any], system: Any = None, **kwargs: Any) -> Any:
        call_kwargs: dict[str, Any] = dict(kwargs)
        call_kwargs["messages"] = mask_messages(messages, self.masker)
        if system is not None:
            call_kwargs["system"] = mask_system(system, self.masker)
        response = self.client.messages.create(**call_kwargs)
        return restore_message(response, self.masker)

    def stream(
        self, *, messages: list[Any], system: Any = None, **kwargs: Any
    ) -> VeilMessageStream:
        call_kwargs: dict[str, Any] = dict(kwargs)
        call_kwargs["messages"] = mask_messages(messages, self.masker)
        if system is not None:
            call_kwargs["system"] = mask_system(system, self.masker)
        raw_stream = self.client.messages.stream(**call_kwargs)
        return VeilMessageStream(raw_stream, self.masker)
