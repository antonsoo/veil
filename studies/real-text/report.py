"""Print the study's tables from results.json.

    python3 studies/real-text/report.py
    python3 studies/real-text/report.py --before 0.4.4 --after checkout

Every number in README.md is one of these.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
TYPES = ("SECRET", "CARD", "IPV6", "IPV4", "PHONE", "EMAIL", "URL_CREDENTIAL")
GROUPS = (
    ("System logs (Loghub)", lambda name: name == "loghub"),
    ("CI build logs", lambda name: name == "kubernetes"),
    ("Source trees", lambda name: name.startswith("code")),
)


def grouped(part: dict[str, Any]) -> list[tuple[str, int, int, Counter[str]]]:
    rows = []
    for title, belongs in GROUPS:
        chosen = [corpus for name, corpus in part.items() if belongs(name)]
        if chosen:
            counts: Counter[str] = Counter()
            for corpus in chosen:
                counts.update(corpus["by_type"])
            rows.append(
                (title, sum(c["files"] for c in chosen), sum(c["words"] for c in chosen), counts)
            )
    return rows


def technical(results: dict[str, Any], before: str, after: str, part: str) -> None:
    print(f"\n### {part}\n")
    print(
        "| Text | Files | Words | "
        + " | ".join(f"{kind}: {before} | now" for kind in TYPES[:5])
        + " |"
    )
    print("|---|---:|---:|" + "---:|---:|" * 5)
    old_rows, new_rows = grouped(results[before][part]), grouped(results[after][part])
    total_old: Counter[str] = Counter()
    total_new: Counter[str] = Counter()
    files = words = 0
    for (title, n_files, n_words, old), (_, _, _, new) in zip(old_rows, new_rows, strict=True):
        cells = " | ".join(f"{old[kind]:,} | {new[kind]:,}" for kind in TYPES[:5])
        print(f"| {title} | {n_files} | {n_words:,} | {cells} |")
        total_old.update(old)
        total_new.update(new)
        files += n_files
        words += n_words
    cells = " | ".join(f"{total_old[kind]:,} | {total_new[kind]:,}" for kind in TYPES[:5])
    print(f"| **All** | {files} | {words:,} | {cells} |")
    for label, total in ((before, total_old), (after, total_new)):
        three = total["SECRET"] + total["CARD"] + total["IPV6"]
        print(
            f"\n{label}: SECRET + CARD + IPV6 = {three:,}, {1000 * three / words:.2f} per 1,000 words;",
            end=" ",
        )
        print(
            f"EMAIL {total['EMAIL']:,}, URL_CREDENTIAL {total['URL_CREDENTIAL']:,}, all types {sum(total.values()):,}"
        )


def phone_totals(part: dict[str, Any]) -> Counter[str]:
    totals: Counter[str] = Counter()
    for counts in part["phones"].values():
        totals.update(counts)
    return totals


def share(found: int, of: int) -> str:
    return f"{100 * found / of:.1f}%" if of else "–"


def osm(results: dict[str, Any], before: str, after: str, part: str) -> None:
    old, new = results[before][part], results[after][part]
    print(f"\n### {part}: {new['places']:,} places, {new['words']:,} words\n")
    print(f"| Country | Numbers written with + | {before} | now | Without + | {before} | now |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    order = sorted(
        new["phones"],
        key=lambda c: (
            old["phones"][c].get("international: found", 0)
            / max(1, sum(v for k, v in old["phones"][c].items() if k.startswith("international")))
        ),
    )
    for country in order:
        o, n = old["phones"][country], new["phones"][country]
        plus = sum(v for k, v in n.items() if k.startswith("international"))
        bare = sum(v for k, v in n.items() if k.startswith("national"))
        print(
            f"| {country} | {plus:,} | {share(o.get('international: found', 0), plus)} | {share(n.get('international: found', 0), plus)} "
            f"| {bare} | {o.get('national: found', 0)} | {n.get('national: found', 0)} |"
        )
    to, tn = phone_totals(old), phone_totals(new)
    plus = sum(v for k, v in tn.items() if k.startswith("international"))
    bare = sum(v for k, v in tn.items() if k.startswith("national"))
    print(
        f"| **All** | {plus:,} | {share(to['international: found'], plus)} | {share(tn['international: found'], plus)} "
        f"| {bare} | {to['national: found']} | {tn['national: found']} |"
    )
    for label, totals, run in ((before, to, old), (after, tn, new)):
        print(f"\n{label}: {dict(sorted(totals.items()))}")
        emails = run["emails"]
        of = sum(v for k, v in emails.items() if k != "not an address")
        print(
            f"  emails: {emails.get('found', 0):,} of {of:,} found ({share(emails.get('found', 0), of)}); {emails}"
        )
        print(f"  masked outside phone and email tags: {run['elsewhere']}")
        for kind, keys in run["elsewhere_keys"].items():
            print(f"    {kind}: {keys}")
        for country, counts in run["addresses"].items():
            of = sum(counts.values())
            print(
                f"  address lines, {country}: {counts.get('found', 0):,} of {of:,} whole ({share(counts.get('found', 0), of)}); {counts}"
            )
    baseline = results.get("libphonenumber", {}).get(part)
    if baseline:
        for mode in ("no region", "told the country"):
            counts = baseline[mode]
            plus = sum(v for k, v in counts.items() if k.startswith("international"))
            bare = sum(v for k, v in counts.items() if k.startswith("national"))
            print(
                f"\nlibphonenumber, {mode}: with + {share(counts.get('international: found', 0), plus)} of {plus:,}; "
                f"without + {counts.get('national: found', 0)} of {bare}; elsewhere {baseline['elsewhere'][mode]}"
            )


def tokens(results: dict[str, Any], before: str, after: str) -> None:
    print("\n### random tokens masked whole\n")
    old, new = results[before]["random_tokens"], results[after]["random_tokens"]
    lengths = list(next(iter(new.values())))
    print("| Alphabet | " + " | ".join(f"{n} chars: {before} | now" for n in lengths) + " |")
    print("|---|" + "---:|---:|" * len(lengths))
    for name in new:
        print(
            f"| {name} | "
            + " | ".join(f"{old[name][n]}% | {new[name][n]}%" for n in lengths)
            + " |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--before", default="0.4.4")
    parser.add_argument("--after", default="checkout")
    args = parser.parse_args()
    results = json.loads((HERE / "results.json").read_text())
    for part in ("technical", "technical_heldout"):
        if part in results[args.after] and part in results[args.before]:
            technical(results, args.before, args.after, part)
    for part in ("osm", "osm_heldout"):
        if part in results[args.after] and part in results[args.before]:
            osm(results, args.before, args.after, part)
    tokens(results, args.before, args.after)


if __name__ == "__main__":
    main()
