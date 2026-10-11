"""Shared helpers for the Anthropic and OpenAI wrappers: masking/restoring
values inside arbitrary JSON-shaped message and tool-argument structures,
regardless of whether the SDK hands us a plain ``dict`` or a pydantic-style
model object.
"""

from __future__ import annotations

import inspect
import json
from collections import OrderedDict
from copy import copy, deepcopy
from dataclasses import dataclass
from typing import Any

from veil.integrations._json_arguments import restore_arguments as restore_arguments
from veil.masker import Masker
from veil.vault import VaultError


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
    obj = copy(obj)
    for key, val in updates.items():
        setattr(obj, key, val)
    return obj


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _plain(value: Any, *, sdk_defaults: bool = False) -> Any:
    """Comparable protocol objects, retaining nulls in application JSON.

    SDK optional model fields may be absent in a reconstructed dictionary.
    Pydantic's exclude_none drops those fields but keeps null dictionary values
    inside tool inputs. Dropping every dictionary null would hide real edits.
    """
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=not sdk_defaults)
    elif (
        not isinstance(value, (dict, list, str, int, float, bool))
        and value is not None
        and hasattr(value, "__dict__")
    ):
        value = vars(value)
    if isinstance(value, dict):
        return {k: _plain(v, sdk_defaults=sdk_defaults) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v, sdk_defaults=sdk_defaults) for v in value]
    return value


def fingerprint(value: Any, *, sdk_defaults: bool = False) -> str:
    return json.dumps(
        _plain(value, sdk_defaults=sdk_defaults), sort_keys=True, ensure_ascii=False, default=str
    )


@dataclass
class _ReplayValue:
    original: Any
    fingerprint: str
    ambiguous: bool = False


@dataclass
class _ReplayObject:
    restored: Any
    fingerprint: str
    value: _ReplayValue


class ReplayCache:
    """Maps what veil handed the application back to exactly what the model produced.

    An application keeps the conversation it saw: assistant turns with real values restored. On the
    next request those turns go back to the API, and re-masking them only approximates the original -
    a value the model wrote itself that happens to look like PII gets a fresh surrogate, a tolerant
    restore of a mangled surrogate doesn't round-trip. Any difference edits an
    earlier turn and can interrupt prompt-cache reuse. Replaying the remembered
    original keeps the history as the provider returned it.

    Distinct originals can restore to identical text. Retained list/dict/SDK
    objects carry their own identity; reconstructed values can use a content
    match only while that match is unambiguous and no content has been evicted.
    Plain strings have no reliable
    occurrence identity. An ambiguous lookup fails before transport instead of
    choosing another turn's spelling. Both indexes are bounded by max_entries;
    exact replay is limited to retained, unchanged entries in this wrapper.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._entries: OrderedDict[str, _ReplayValue] = OrderedDict()
        self._objects: OrderedDict[int, _ReplayObject] = OrderedDict()
        self._max_entries = max_entries
        self._content_history_complete = True

    def remember(self, restored: Any, original: Any) -> None:
        key = fingerprint(restored)
        value = _ReplayValue(deepcopy(original), fingerprint(original))
        # Recognize both SDK model_dump() and model_dump(exclude_none=True),
        # without dropping nulls from application dictionaries in either form.
        for content_key in dict.fromkeys((key, fingerprint(restored, sdk_defaults=True))):
            existing = self._entries.get(content_key)
            if existing is None:
                self._entries[content_key] = value
            elif existing.fingerprint != value.fingerprint:
                existing.ambiguous = True
            self._entries.move_to_end(content_key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
            # A later equal value may have had a different original in the
            # forgotten history. Bounded memory cannot prove uniqueness again.
            self._content_history_complete = False

        # Strings may be interned, or restoration may return the same vault
        # string for several turns. Only containers have occurrence identity.
        if isinstance(restored, (list, dict)) or hasattr(restored, "__dict__"):
            prior = self._objects.get(id(restored))
            if prior is not None and prior.fingerprint == key:
                if prior.value.fingerprint != value.fingerprint:
                    prior.value.ambiguous = True
            else:
                # Do not share the ambiguity flag with the content index:
                # this exact object still identifies its original occurrence.
                identity_value = _ReplayValue(value.original, value.fingerprint)
                self._objects[id(restored)] = _ReplayObject(restored, key, identity_value)
            self._objects.move_to_end(id(restored))
            while len(self._objects) > self._max_entries:
                self._objects.popitem(last=False)

    def original_for(self, value: Any, *, identity_only: bool = False) -> Any | None:
        key = fingerprint(value)
        identity = self._objects.get(id(value))
        entry: _ReplayValue | None
        if identity is not None and identity.restored is value:
            if identity.fingerprint != key:
                return None  # The application edited this object: mask it afresh.
            entry = identity.value
        else:
            if identity_only:
                return None
            entry = self._entries.get(key)
            if entry is not None and (entry.ambiguous or not self._content_history_complete):
                # Rebuilding a content list need not lose the identities of its
                # blocks. Every block must still be unchanged and retained.
                if isinstance(value, list) and value:
                    originals = [self.original_for(item, identity_only=True) for item in value]
                    if all(item is not None for item in originals):
                        return originals
                if not self._content_history_complete:
                    raise VaultError(
                        "Replay cache capacity was exceeded; copied or plain-text assistant "
                        "history can no longer be identified safely. Keep unchanged returned "
                        "message/content objects while retained, or begin a new conversation."
                    )
        if entry is None:
            return None
        if entry.ambiguous:
            raise VaultError(
                "Ambiguous assistant history: different provider replies restored to the same "
                "content. Keep the original restored content/message objects in history instead "
                "of reconstructing them or storing plain text. Exact replay cannot choose a turn."
            )
        # Neither SDK snapshots nor a caller editing prepared history may change
        # the remembered provider value.
        return deepcopy(entry.original)

    def __len__(self) -> int:
        return len(self._entries)
