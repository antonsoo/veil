"""Compare retained installed-wheel audit classifications."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    before = json.loads((HERE / "results/before-installed.json").read_text())
    after = json.loads((HERE / "results/installed-python312.json").read_text())
    print("Veil: known containers and new PII, installed Python 3.12 wheels")
    print("Synthetic inputs; original-leak tuples must remain identical")
    print()
    print(f"{'Case':34} {'Before new':>11} {'After new':>10} {'Known leaks':>12}")
    print("-" * 70)
    for old, new in zip(before["cases"], after["cases"], strict=True):
        for key in ("case", "text", "vault", "expectedNewValues", "leakedOriginals"):
            assert old[key] == new[key]
        assert new["expectedNewValuesMatch"]
        print(
            f"{new['case']:34} {len(old['newPii']):11} "
            f"{len(new['newPii']):10} {len(new['leakedOriginals']):12}"
        )
    print()
    print(
        f"Declared case expectations: {before['passedCases']}/{before['totalCases']} -> "
        f"{after['passedCases']}/{after['totalCases']}"
    )
    for old, new in zip(before["cases"], after["cases"], strict=True):
        if "cli" in old:
            print(
                f"CLI {new['case']}: exit {old['cli']['exitCode']} -> {new['cli']['exitCode']}; "
                f"findings {len(old['cli']['findings'])} -> {len(new['cli']['findings'])}"
            )
    print("New candidates crossing a known boundary remain visible.")
    print("Explicit [] disables new-PII detectors; original leaks still count.")


if __name__ == "__main__":
    main()
