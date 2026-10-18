"""Derive complete single-transaction HAR views within a consumer's input limit.

This selects and compactly serializes native JSON values; outputs are derived
views, never claimed to be unchanged producer files or independent requests.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--fixtures", type=Path, default=Path(__file__).parent / "fixtures")
    parser.add_argument("--max-chars", type=int, default=12000)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    oracle_bytes = (args.fixtures / "oracle.json").read_bytes()
    oracle = json.loads(oracle_bytes)
    cases = []
    for item in oracle["rows"]:
        raw = (args.fixtures / item["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        original = json.loads(raw)
        for index, entry in enumerate(original["log"]["entries"]):
            prefix = f"/log/entries/{index}/"
            surfaces = [
                {**surface, "path": surface["path"].replace(prefix, "/log/entries/0/", 1)}
                for surface in item["surfaces"]
                if surface["path"].startswith(prefix)
            ]
            if not surfaces:
                continue
            view = copy.deepcopy(original)
            view["log"]["entries"] = [copy.deepcopy(entry)]
            assert view["log"]["entries"][0] == entry
            source = json.dumps(view, ensure_ascii=False, separators=(",", ":"))
            if len(source) > args.max_chars:
                raise ValueError(
                    "A complete transaction exceeds the requested bound; no values were truncated"
                )
            path = urlsplit(entry["request"]["url"]).path.strip("/")
            name = f"{item['engine']}-{index}-{path}"
            (args.out / (name + ".har")).write_text(source)
            cases.append(
                {
                    "name": name,
                    "file": name + ".har",
                    "path": path,
                    "producer": item["engine"],
                    "parentFile": item["file"],
                    "parentSha256": item["sha256"],
                    "originalEntryIndex": index,
                    "sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "characters": len(source),
                    "surfaces": surfaces,
                }
            )
    receipt = {
        "scope": __doc__,
        "parentOracleSha256": hashlib.sha256(oracle_bytes).hexdigest(),
        "maxCharacters": args.max_chars,
        "cases": cases,
    }
    (args.out / "views.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {"derivedViews": len(cases), "maxCharacters": max(c["characters"] for c in cases)}
        )
    )


if __name__ == "__main__":
    main()
