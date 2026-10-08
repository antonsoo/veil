"""Draw figures/phones-{light,dark}.svg from results.json.

    python3 studies/real-text/figures.py

One row per country: the share of phone numbers written with a "+" that veil
masked, in 0.4.4 and in this checkout. Development countries first, then the
countries that appear only in the held-out cities.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
NAMES = {
    "AR": "Argentina", "AT": "Austria", "AU": "Australia", "BE": "Belgium", "BR": "Brazil", "CA": "Canada",
    "CH": "Switzerland", "CL": "Chile", "CO": "Colombia", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark",
    "ES": "Spain", "FR": "France", "GB": "United Kingdom", "HK": "Hong Kong", "ID": "Indonesia", "IE": "Ireland",
    "IN": "India", "IT": "Italy", "JP": "Japan", "KE": "Kenya", "KR": "South Korea", "MX": "Mexico",
    "NL": "Netherlands", "NZ": "New Zealand", "PL": "Poland", "PT": "Portugal", "SE": "Sweden", "SG": "Singapore",
    "TH": "Thailand", "TR": "Turkey", "TW": "Taiwan", "US": "United States", "ZA": "South Africa",
}  # fmt: skip
THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#1f1e1c",
        "muted": "#6f6d68",
        "grid": "#e4e2dc",
        "old": "#d95926",
        "new": "#2a78d6",
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#ecebe7",
        "muted": "#a3a19a",
        "grid": "#34332f",
        "old": "#eb6834",
        "new": "#3987e5",
    },
}
WIDTH, LEFT, RIGHT, ROW = 760, 150, 640, 20


def shares(part: dict[str, Any]) -> dict[str, tuple[int, float]]:
    out = {}
    for country, counts in part["phones"].items():
        total = sum(n for outcome, n in counts.items() if outcome.startswith("international"))
        if total >= 30:
            out[country] = (total, 100 * counts.get("international: found", 0) / total)
    return out


def rows(results: dict[str, Any], part: str) -> list[tuple[str, int, float, float]]:
    old, new = shares(results["0.4.4"][part]), shares(results["checkout"][part])
    return sorted(
        ((c, new[c][0], old[c][1], new[c][1]) for c in new if c in old), key=lambda row: row[2]
    )


def x(share: float) -> float:
    return LEFT + (RIGHT - LEFT) * share / 100


def draw(
    theme: dict[str, str], groups: list[tuple[str, list[tuple[str, int, float, float]]]]
) -> str:
    height = 54 + sum(54 + ROW * len(group) for _, group in groups)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" height="{height}" '
        f'role="img" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">',
        "<title>Share of phone numbers written with a + that veil masked, by country, in 0.4.4 and in this checkout</title>",
        f'<rect width="{WIDTH}" height="{height}" fill="{theme["surface"]}"/>',
        f'<circle cx="{LEFT + 6}" cy="20" r="5" fill="{theme["old"]}"/>'
        f'<text x="{LEFT + 17}" y="24" fill="{theme["ink"]}">veil 0.4.4</text>',
        f'<circle cx="{LEFT + 106}" cy="20" r="5" fill="{theme["new"]}"/>'
        f'<text x="{LEFT + 117}" y="24" fill="{theme["ink"]}">this checkout</text>',
        f'<text x="{WIDTH - 12}" y="24" fill="{theme["muted"]}" text-anchor="end">numbers</text>',
    ]
    y = 44
    for title, group in groups:
        out.append(
            f'<text x="12" y="{y + 12}" fill="{theme["ink"]}" font-weight="600">{title}</text>'
        )
        y += 24
        top = y
        for tick in (0, 25, 50, 75, 100):
            out.append(
                f'<line x1="{x(tick):.1f}" y1="{top}" x2="{x(tick):.1f}" y2="{top + ROW * len(group)}" stroke="{theme["grid"]}"/>'
            )
        for country, total, before, after in group:
            mid = y + ROW / 2
            out.append(
                f'<text x="{LEFT - 12}" y="{mid + 4}" fill="{theme["ink"]}" text-anchor="end">{NAMES.get(country, country)}</text>'
            )
            out.append(
                f'<line x1="{x(before):.1f}" y1="{mid}" x2="{x(after):.1f}" y2="{mid}" stroke="{theme["muted"]}" stroke-width="2"/>'
            )
            out.append(
                f'<circle cx="{x(before):.1f}" cy="{mid}" r="5" fill="{theme["old"]}" stroke="{theme["surface"]}" stroke-width="2">'
                f"<title>{NAMES.get(country, country)}, 0.4.4: {before:.1f}% of {total:,}</title></circle>"
            )
            out.append(
                f'<circle cx="{x(after):.1f}" cy="{mid}" r="5" fill="{theme["new"]}" stroke="{theme["surface"]}" stroke-width="2">'
                f"<title>{NAMES.get(country, country)}, this checkout: {after:.1f}% of {total:,}</title></circle>"
            )
            if before < 5:  # no room on the left: write it over the line, on a patch of surface
                out.append(
                    f'<text x="{x(before) + 10:.1f}" y="{mid + 4}" fill="{theme["muted"]}" stroke="{theme["surface"]}" '
                    f'stroke-width="5" paint-order="stroke">{before:.0f}%</text>'
                )
            elif before < 88:
                out.append(
                    f'<text x="{x(before) - 10:.1f}" y="{mid + 4}" fill="{theme["muted"]}" text-anchor="end">{before:.0f}%</text>'
                )
            out.append(
                f'<text x="{WIDTH - 12}" y="{mid + 4}" fill="{theme["muted"]}" text-anchor="end">{total:,}</text>'
            )
            y += ROW
        for tick in (0, 50, 100):
            out.append(
                f'<text x="{x(tick):.1f}" y="{y + 14}" fill="{theme["muted"]}" text-anchor="middle">{tick}%</text>'
            )
        y += 30
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    results = json.loads((HERE / "results.json").read_text())
    groups = [("Cities the detector was changed against", rows(results, "osm"))]
    if "osm_heldout" in results["checkout"] and "osm_heldout" in results["0.4.4"]:
        groups.append(("Cities held out", rows(results, "osm_heldout")))
    (HERE / "figures").mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (HERE / "figures" / f"phones-{name}.svg").write_text(draw(theme, groups), encoding="utf-8")
        print(f"figures/phones-{name}.svg")


if __name__ == "__main__":
    main()
