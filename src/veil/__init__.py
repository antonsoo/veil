"""veil: reversible PII masking for LLM calls.

Mask personal data before a prompt leaves your network, let the model
reason over consistent surrogates, and restore the originals in the
response — including from a token stream.

Typical usage::

    from veil import Masker

    masker = Masker()
    masked = masker.mask("Email alice@example.com about invoice #4471.")
    # -> "Email ⟨EMAIL_1⟩ about invoice #4471."

    reply = call_llm(masked)  # the model never sees the real address
    restored = masker.restore(reply)  # exact + tolerant restore

See :mod:`veil.masker`, :mod:`veil.restore`, :mod:`veil.vault`, and
:mod:`veil.audit` for the full pipeline, and :mod:`veil.integrations` for
thin Anthropic/OpenAI SDK wrappers.
"""

from __future__ import annotations

from veil.audit import LeakFinding, audit, find_leaked_originals, find_new_pii
from veil.masker import Masker
from veil.restore import Restorer, restore_exact, restore_tolerant
from veil.surrogates import PlaceholderSurrogates, RealisticSurrogates
from veil.types import Entity, EntityType, Mapping, Span
from veil.vault import Vault, VaultError

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Masker",
    "Vault",
    "VaultError",
    "Restorer",
    "restore_exact",
    "restore_tolerant",
    "PlaceholderSurrogates",
    "RealisticSurrogates",
    "Entity",
    "EntityType",
    "Mapping",
    "Span",
    "LeakFinding",
    "audit",
    "find_leaked_originals",
    "find_new_pii",
]
