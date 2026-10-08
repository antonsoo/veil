"""The same places through libphonenumber's matcher, to place veil's numbers.

    uv run --with phonenumbers==9.0.40 python studies/real-text/baseline_phonenumbers.py

Google's libphonenumber is the reference implementation for parsing phone
numbers; `phonenumbers` is its Python port, and `PhoneNumberMatcher` is its
finder of numbers in running text. Like veil it is run here twice over the
OpenStreetMap places: with no region, where it can only know a number written
with a `+`, and told each place's country, which veil has no way to be.

Counts what veil's evaluation counts (evaluate.py): for each value a tag key
labels as a phone number, whether a match covers all its digits.
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

import phonenumbers

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("evaluate", HERE / "evaluate.py")
assert spec is not None and spec.loader is not None
evaluate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluate)


def run(manifest_name: str) -> dict[str, Any]:
    manifest = json.loads((HERE / manifest_name).read_text())
    out: dict[str, Counter[str]] = {"no region": Counter(), "told the country": Counter()}
    elsewhere: Counter[str] = Counter()
    for city in manifest["cities"]:
        elements = json.loads((evaluate.CACHE / "osm" / city["file"]).read_text(encoding="utf-8"))[
            "elements"
        ]
        for element in evaluate.sample(elements):
            line, gold = evaluate.render(element)
            phones = [
                g for g in gold if g["kind"] == "phone" and len(evaluate.digits(g["value"])) >= 7
            ]
            for mode, region in (("no region", None), ("told the country", city["country"])):
                matches = [(m.start, m.end) for m in phonenumbers.PhoneNumberMatcher(line, region)]
                for item in phones:
                    wanted = [i for i in range(item["start"], item["end"]) if line[i].isdigit()]
                    covered = [i for i in wanted if any(start <= i < end for start, end in matches)]
                    outcome = (
                        "found"
                        if len(covered) == len(wanted)
                        else "partly"
                        if covered
                        else "missed"
                    )
                    out[mode][f"{evaluate.phone_class(item['value'])}: {outcome}"] += 1
                spans = [(g["start"], g["end"]) for g in gold]
                elsewhere[mode] += sum(
                    1 for start, end in matches if not any(start < e and s < end for s, e in spans)
                )
    return {mode: dict(sorted(counts.items())) for mode, counts in out.items()} | {
        "elsewhere": dict(elsewhere)
    }


def main() -> None:
    results_path = HERE / "results.json"
    results = json.loads(results_path.read_text())
    baseline: dict[str, Any] = {
        "phonenumbers": phonenumbers.__version__,
        "osm": run("manifest-osm.json"),
    }
    if (HERE / "manifest-osm-heldout.json").exists():
        baseline["osm_heldout"] = run("manifest-osm-heldout.json")
    results["libphonenumber"] = baseline
    results_path.write_text(
        json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(baseline, indent=1))


if __name__ == "__main__":
    main()
