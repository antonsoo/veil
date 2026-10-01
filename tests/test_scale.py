"""Masking and restoring must stay roughly linear in the size of the text.

A customer export or a long log holds thousands of values. Each bound below is
many times what the code needs and far below what a quadratic step would take:
before these were fixed, the first test took about 50 seconds and the repeated
``a.`` input about a minute.
"""

from __future__ import annotations

import time

import pytest

from veil.detectors import all_detectors
from veil.masker import Masker


def _export(rows: int) -> str:
    return "\n".join(
        f"{i},user{i}@corp{i % 97}.io,+1 415 555 {1000 + i % 9000:04d},"
        f"10.{i % 250}.{i // 250 % 250}.{i % 199 + 1},born 0{i % 9 + 1}/1{i % 9}/19{60 + i % 40}"
        for i in range(rows)
    )


def test_a_large_export_masks_and_restores_in_seconds() -> None:
    text = _export(4000)  # about 270 KB, 16,000 values
    masker = Masker()
    started = time.perf_counter()
    masked = masker.mask(text)
    restored = masker.restore(masked)
    elapsed = time.perf_counter() - started
    assert len(masker.vault) > 10_000
    assert restored == text
    assert elapsed < 15, f"took {elapsed:.1f} s"


_DASHES = "-" * 5
_REPEATED = [
    "a.",
    "a-",
    "a+",
    "a@a.",
    "x://",
    "_://",
    "1 ",
    "1-",
    "1:",
    "born 1/1/1990 ",
    f"{_DASHES}BEGIN PRIVATE KEY{_DASHES}\n!",
    f"{_DASHES}BEGIN A PRIVATE KEY{_DASHES}{_DASHES}END B PRIVATE KEY{_DASHES}",
    "A ",
    "DE00 ",
    "=A/",
    "x://" + ":" * 199_996,
    "x://" + "u:p" * 66_665,
    "x://h/?" + "&token" * 33_332,
]


@pytest.mark.parametrize("unit", _REPEATED, ids=lambda unit: unit[:24])
def test_repetitive_input_does_not_stall_a_detector(unit: str) -> None:
    text = unit * max(1, 200_000 // len(unit))
    started = time.perf_counter()
    for detector in all_detectors():
        detector.find(text)
    elapsed = time.perf_counter() - started
    assert elapsed < 10, f"took {elapsed:.1f} s"
