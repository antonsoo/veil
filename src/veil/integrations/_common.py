"""Shared helpers for the Anthropic and OpenAI wrappers: masking/restoring
values inside arbitrary JSON-shaped message and tool-argument structures,
regardless of whether the SDK hands us a plain ``dict`` or a pydantic-style
model object.
"""

from __future__ import annotations

import inspect
import json
from collections import OrderedDict
from typing import Any

from veil.masker import Masker
from veil.restore import restore_json_text


def mask_value(value: Any, masker: Masker) -> Any:
    """Recursively mask every string found in a JSON-shaped value."""
    if isinstance(value, str):
        return masker.mask(value)
    if isinstance(value, list):
        return [mask_value(v, masker) for v in value]
    if isinstance(value, dict):
        return {k: mask_value(v, masker) for k, v in value.items()}
    return value


def restore_value(value: Any, masker: Masker, *, tolerant: bool = True) -> Any:
    """Recursively restore every string found in a JSON-shaped value."""
    if isinstance(value, str):
        return masker.restore(value, tolerant=tolerant)
    if isinstance(value, list):
        return [restore_value(v, masker, tolerant=tolerant) for v in value]
    if isinstance(value, dict):
        return {k: restore_value(v, masker, tolerant=tolerant) for k, v in value.items()}
    return value


def restore_arguments(arguments: str, masker: Masker) -> str:
    """Restore a complete tool-call ``arguments`` JSON string.

    Parsed, restored value by value and re-serialized, so the restore doesn't
    depend on how the model escaped the surrogate (``\\u27e8`` for ``⟨``).
    """
    try:
        parsed = json.loads(arguments)
    except ValueError:
        return restore_json_text(arguments, masker.vault)  # truncated or not JSON: best effort
    restored = restore_value(parsed, masker)
    return arguments if restored == parsed else json.dumps(restored, ensure_ascii=False)


def needs_await(method: Any) -> bool:
    """True when calling ``method`` returns a coroutine: a method of an SDK's async client.

    Both SDKs wrap their ``create`` methods in a plain decorator, so the coroutine
    function is only visible underneath it.
    """
    if method is None:
        return False
    try:
        method = inspect.unwrap(method)
    except ValueError:  # a cycle of __wrapped__: not something an SDK produces
        return False
    return inspect.iscoroutinefunction(method)


def model_copy_with(obj: Any, **updates: Any) -> Any:
    """Return a copy of ``obj`` with ``updates`` applied, whatever shape it is:
    a pydantic-style model (has ``model_copy``), a plain ``dict``, or a
    generic attribute-bearing object (e.g. ``types.SimpleNamespace``, as used
    by the fakes in this project's own tests, and often by other SDKs' test
    doubles too).
    """
    if hasattr(obj, "model_copy"):
        return obj.model_copy(update=updates)
    if isinstance(obj, dict):
        return {**obj, **updates}
    for key, val in updates.items():
        setattr(obj, key, val)
    return obj


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _plain(value: Any) -> Any:
    """A JSON-comparable form of an SDK object, dict, or scalar, with ``None`` fields dropped (an SDK
    model dumps absent optionals as ``None``; the same block rebuilt as a dict usually omits them)."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif (
        not isinstance(value, (dict, list, str, int, float, bool))
        and value is not None
        and hasattr(value, "__dict__")
    ):
        value = vars(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def fingerprint(value: Any) -> str:
    return json.dumps(_plain(value), sort_keys=True, ensure_ascii=False, default=str)


class ReplayCache:
    """Maps what veil handed the application back to exactly what the model produced.

    An application keeps the conversation it saw: assistant turns with real values restored. On the
    next request those turns go back to the API, and re-masking them only approximates the original -
    a value the model wrote itself that happens to look like PII gets a fresh surrogate, a tolerant
    restore of a mangled surrogate doesn't round-trip. Any difference is an edit to an earlier turn:
    it restarts the prompt cache from that point, and on current Claude models it invalidates the
    signature of every later thinking block (a 400 on accounts that enforce the check). Replaying the
    remembered original instead keeps the history byte-identical to what the provider returned.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: OrderedDict[str, Any] = OrderedDict()
        self._max_entries = max_entries

    def remember(self, restored: Any, original: Any) -> None:
        key = fingerprint(restored)
        self._entries[key] = original
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def original_for(self, value: Any) -> Any | None:
        return self._entries.get(fingerprint(value))

    def __len__(self) -> int:
        return len(self._entries)
