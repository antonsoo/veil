"""Shared helpers for the Anthropic and OpenAI wrappers: masking/restoring
values inside arbitrary JSON-shaped message and tool-argument structures,
regardless of whether the SDK hands us a plain ``dict`` or a pydantic-style
model object.
"""

from __future__ import annotations

from typing import Any

from veil.masker import Masker


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
