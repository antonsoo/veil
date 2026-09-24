#!/usr/bin/env python3
"""Evaluate veil's built-in detectors against the synthetic corpus, and
measure masking throughput and streaming-restore latency overhead on this
machine.

Usage:
    uv run python scripts/generate_corpus.py 40 > benchmarks/corpus.jsonl
    uv run python scripts/evaluate.py benchmarks/corpus.jsonl

Matching is exact-span: a predicted entity counts as a true positive only
if its (type, start, end) matches a ground-truth entity exactly. This is
the strict, unambiguous reading of "the detector found *this* PII" - it
does not give credit for a near-miss span. Person/org/location names are
excluded (see `generate_corpus.py` docstring): they're backend-driven, not
part of what these regex detectors claim to do.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from veil.detectors import all_detectors  # noqa: E402
from veil.masker import Masker  # noqa: E402
from veil.restore import Restorer, restore_exact  # noqa: E402


def load_corpus(path: str) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def evaluate_detectors(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    detectors = all_detectors()
    counts: dict[str, dict[str, int]] = {}

    def bucket(etype: str) -> dict[str, int]:
        return counts.setdefault(etype, {"tp": 0, "fp": 0, "fn": 0})

    for row in rows:
        text = row["text"]
        gold = {(e["type"], e["start"], e["end"]) for e in row["entities"]}
        gold_types = {e["type"] for e in row["entities"]}
        predicted = set()
        for detector in detectors:
            for entity in detector.find(text):
                predicted.add((entity.type.value, entity.span.start, entity.span.end))

        all_types = gold_types | {t for t, _, _ in predicted}
        for etype in all_types:
            gold_e = {g for g in gold if g[0] == etype}
            pred_e = {p for p in predicted if p[0] == etype}
            b = bucket(etype)
            b["tp"] += len(gold_e & pred_e)
            b["fp"] += len(pred_e - gold_e)
            b["fn"] += len(gold_e - pred_e)
    return counts


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else float("nan")
    return precision, recall, f1


def measure_throughput(rows: list[dict[str, Any]], repeats: int = 5) -> dict[str, float]:
    texts = [r["text"] for r in rows]
    total_bytes = sum(len(t.encode("utf-8")) for t in texts) * repeats

    start = time.perf_counter()
    for _ in range(repeats):
        for text in texts:
            Masker().mask(text)
    elapsed = time.perf_counter() - start

    mb_per_s = (total_bytes / (1024 * 1024)) / elapsed
    return {"mb_per_s": mb_per_s, "elapsed_s": elapsed, "total_mb": total_bytes / (1024 * 1024)}


def measure_streaming_overhead(
    rows: list[dict[str, Any]], chunk_size: int = 24
) -> dict[str, float]:
    """Compare restoring a masked reply in one shot vs. streamed in fixed
    chunks. The two should already be correct-equivalent (see the
    Hypothesis property tests) - this only measures the speed delta.
    """
    masker = Masker()
    masked_texts = [masker.mask(r["text"]) for r in rows]

    start = time.perf_counter()
    for text in masked_texts:
        restore_exact(text, masker.vault)
    non_streamed_s = time.perf_counter() - start

    start = time.perf_counter()
    for text in masked_texts:
        restorer = Restorer(masker.vault)
        parts = [restorer.feed(text[i : i + chunk_size]) for i in range(0, len(text), chunk_size)]
        parts.append(restorer.flush())
        "".join(parts)
    streamed_s = time.perf_counter() - start

    overhead_pct = (
        (streamed_s - non_streamed_s) / non_streamed_s * 100 if non_streamed_s else float("nan")
    )
    return {
        "non_streamed_s": non_streamed_s,
        "streamed_s": streamed_s,
        "overhead_pct": overhead_pct,
        "chunk_size": chunk_size,
    }


def main() -> None:
    corpus_path = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/corpus.jsonl"
    rows = load_corpus(corpus_path)
    print(f"Corpus: {corpus_path} ({len(rows)} documents, all synthetic)\n")

    counts = evaluate_detectors(rows)
    print(f"{'type':<16}{'tp':>6}{'fp':>6}{'fn':>6}{'precision':>12}{'recall':>10}{'f1':>8}")
    totals = {"tp": 0, "fp": 0, "fn": 0}
    for etype in sorted(counts):
        c = counts[etype]
        p, r, f1 = precision_recall_f1(c["tp"], c["fp"], c["fn"])
        print(f"{etype:<16}{c['tp']:>6}{c['fp']:>6}{c['fn']:>6}{p:>12.3f}{r:>10.3f}{f1:>8.3f}")
        for k in totals:
            totals[k] += c[k]
    p, r, f1 = precision_recall_f1(totals["tp"], totals["fp"], totals["fn"])
    print(
        f"{'TOTAL':<16}{totals['tp']:>6}{totals['fp']:>6}{totals['fn']:>6}{p:>12.3f}{r:>10.3f}{f1:>8.3f}"
    )

    print(f"\nMachine: {platform.platform()}, Python {platform.python_version()}")

    tp = measure_throughput(rows)
    print(
        f"\nMasking throughput: {tp['mb_per_s']:.2f} MB/s ({tp['total_mb']:.2f} MB in {tp['elapsed_s']:.3f}s)"
    )

    ov = measure_streaming_overhead(rows)
    print(
        f"Streaming restore overhead (chunk={ov['chunk_size']} chars): "
        f"{ov['overhead_pct']:+.1f}% vs. non-streamed "
        f"({ov['streamed_s']:.3f}s streamed vs {ov['non_streamed_s']:.3f}s non-streamed)"
    )


if __name__ == "__main__":
    main()
