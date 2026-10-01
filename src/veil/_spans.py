"""Overlap queries over spans, by bisection instead of comparing every pair.

A large document can hold tens of thousands of entities; testing each new
span against a list of all the others makes masking quadratic.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections.abc import Iterable

from veil.types import Span


class SpanIndex:
    """A fixed set of spans: does a given span overlap any of them?"""

    def __init__(self, spans: Iterable[Span]) -> None:
        ordered = sorted(spans, key=lambda s: s.start)
        self._starts = [s.start for s in ordered]
        # _reach[i] is the furthest end among the first i + 1 spans.
        self._reach: list[int] = []
        reach = 0
        for span in ordered:
            reach = max(reach, span.end)
            self._reach.append(reach)

    def overlaps(self, span: Span) -> bool:
        before = bisect_left(self._starts, span.end)  # spans starting before this one ends
        return before > 0 and self._reach[before - 1] > span.start


class DisjointSpans:
    """A growing set of spans that never overlap each other: check, then add."""

    def __init__(self) -> None:
        self._spans: list[tuple[int, int]] = []

    def overlaps(self, span: Span) -> bool:
        # Disjoint spans in start order are also in end order, so only the last
        # one starting before this span ends can reach into it.
        before = bisect_left(self._spans, (span.end,))
        return before > 0 and self._spans[before - 1][1] > span.start

    def add(self, span: Span) -> None:
        insort(self._spans, (span.start, span.end))
