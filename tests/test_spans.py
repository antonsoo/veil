"""The bisecting overlap checks must agree with comparing every pair."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from veil._spans import DisjointSpans, SpanIndex
from veil.types import Span

_spans = st.builds(
    lambda start, length: Span(start, start + length),
    st.integers(min_value=0, max_value=60),
    st.integers(min_value=0, max_value=12),
)


@given(st.lists(_spans, max_size=25), _spans)
def test_span_index_matches_pairwise_comparison(spans: list[Span], probe: Span) -> None:
    assert SpanIndex(spans).overlaps(probe) == any(probe.overlaps(s) for s in spans)


@given(st.lists(_spans, max_size=40))
def test_disjoint_spans_keeps_the_same_spans_as_pairwise_comparison(spans: list[Span]) -> None:
    kept: list[Span] = []
    taken = DisjointSpans()
    for span in spans:
        expected = any(span.overlaps(k) for k in kept)
        assert taken.overlaps(span) == expected
        if not expected:
            kept.append(span)
            taken.add(span)
