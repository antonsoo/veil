"""Print the retained installed-wheel comparison, checking every result hash."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    before = json.loads((HERE / "results/before.json").read_text())
    extra = json.loads((HERE / "results/prefix-control-before.json").read_text())
    after = json.loads((HERE / "results/installed-python312.json").read_text())
    assert before["python"] == extra["python"] == after["python"] == "3.12.12"
    previous = {case["case"]: case for case in [*before["cases"], *extra["cases"]]}
    print("Veil leak audit: installed wheels, CPython 3.12.12")
    print("Controlled synthetic identities and URLs; same input/result hashes")
    print()
    print(f"{'Case':28} {'Before ms':>12} {'After ms':>12} {'Findings':>10}")
    print("-" * 65)
    for case in after["cases"]:
        old = previous[case["case"]]
        for key in ("inputSha256", "mappings", "distinctLengths", "count", "sha256"):
            assert old[key] == case[key], (case["case"], key)
        assert case["exactOracleMatch"] and old["exactOracleMatch"]
        print(
            f"{case['case']:28} {old['coldSeconds'] * 1000:12,.2f} "
            f"{case['coldSeconds'] * 1000:12,.2f} {case['count']:10}"
        )
    print()
    for name in ("varied-urls-clean", "varied-urls-leak"):
        old = previous[name]["cli"]
        new = next(case for case in after["cases"] if case["case"] == name)["cli"]
        assert old["exitCode"] == new["exitCode"] and old["sha256"] == new["sha256"]
        print(
            f"CLI {name}: {old['seconds']:.3f}s -> {new['seconds']:.3f}s; "
            f"exit {new['exitCode']}; {new['count']} exact findings"
        )
    print("All 6 cases agree with independent per-value search.")
    print("Cold timings include index construction; single-host observations.")


if __name__ == "__main__":
    main()
