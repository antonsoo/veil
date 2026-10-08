"""Say what the detections in the logs and source code really were.

    python3 studies/real-text/triage.py --label 0.4.4

Reads cache/detections-<label>.jsonl (written by evaluate.py) and sorts the
CARD, IPV6 and IPV4 detections of the technical text into classes by rules
that can be read below. Nothing here uses veil. The result goes to
triage.json under the label.

SECRET detections cannot be sorted by a rule that is not itself a detector,
so a random sample of them was read and labelled by hand instead: see
triage-secret-sample.json.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent


def card_class(row: dict[str, str]) -> str:
    value, before, after = row["value"], row["before"], row["after"]
    if re.search(r"blk_-?$", before):
        return "a block id (blk_…)"
    if re.search(r"[0-9a-f]-$|[a-f]$", before) or (
        re.search(r"[0-9a-f]{4,}-?$", before) and re.search(r"^-?[0-9a-f]{4}", after)
    ):
        return "digits inside a UUID or hex id"
    if " " in value or "-" in value:
        return "several separate numbers: dates, times, process ids, counters"
    if re.search(r"\d\.$", before):
        return "the decimals of a fraction"
    if re.fullmatch(r"1[4-7]\d{11}", value):
        return "a millisecond timestamp"
    if re.fullmatch(r"20\d{12}", value):
        return "a date and time run together"
    if set(value) == {"0"}:
        return "a run of zeros"
    return "another single number: a build id, an integer literal, a duration"


VERSION_BEFORE = re.compile(
    r"(?i)(~|\b(chrome|chromium|edg|edge|opr|firefox|safari|version|applewebkit)/)$"
)


def ip_class(row: dict[str, str]) -> str:
    if VERSION_BEFORE.search(row["before"]):
        return "a version number: a Windows package, a browser"
    address = ipaddress.ip_address(row["value"])
    if address.is_unspecified:
        return "the unspecified address"
    if address.is_loopback:
        return "loopback"
    if address.is_reserved:
        return "reserved space: a slice, a netmask, stray colons"
    if address.is_private:
        return "a private or documentation address"
    return "a public address"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--label", default="0.4.4")
    args = parser.parse_args()

    out: dict[str, Any] = {}
    with (HERE / "cache" / f"detections-{args.label}.jsonl").open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    for part in ("technical", "technical_heldout"):
        chosen = [row for row in rows if row["part"] == part]
        out[part] = {
            "CARD": dict(
                Counter(card_class(row) for row in chosen if row["type"] == "CARD").most_common()
            ),
            "IPV6": dict(
                Counter(ip_class(row) for row in chosen if row["type"] == "IPV6").most_common()
            ),
            # Only the values that are nobody's are listed; a host's address is not repeated here.
            "IPV6 that are no host": dict(
                Counter(
                    row["value"]
                    for row in chosen
                    if row["type"] == "IPV6"
                    and not ip_class(row).startswith(("a private", "a public"))
                ).most_common(8)
            ),
            "IPV4": dict(
                Counter(ip_class(row) for row in chosen if row["type"] == "IPV4").most_common()
            ),
            "EMAIL domains": dict(
                Counter(
                    row["value"].rsplit("@", 1)[-1] for row in chosen if row["type"] == "EMAIL"
                ).most_common(6)
            ),
        }
    path = HERE / "triage.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    results[args.label] = out
    path.write_text(
        json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
