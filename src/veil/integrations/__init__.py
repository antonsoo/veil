"""Thin SDK wrappers that mask outgoing messages and restore responses.

Both integrations are optional extras (``veil-pii[anthropic]`` /
``veil-pii[openai]``) so the core package stays dependency-free; importing
:mod:`veil.integrations` itself never requires either SDK.
"""

from __future__ import annotations
