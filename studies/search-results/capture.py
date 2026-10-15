"""Retain real SDK/mock HTTP retrieval requests; never contact a provider."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import platform
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--label")
    args = parser.parse_args()
    # The test helper supplies transport, fixtures and assertions, never a copy
    # of Veil. Without --source, the library must come from the environment.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    if args.source:
        sys.path.insert(0, str(args.source.resolve() / "src"))
    import anthropic

    from tests.sdk_search_results import EXPECTED_TEXT, MODES, SHAPES, capture

    rows = []
    package_path = None
    for nested, shape, mode, asynchronous in itertools.product(
        [False, True], SHAPES, MODES, [False, True]
    ):
        row = capture(nested, shape, mode, asynchronous)
        package_path = Path(row.pop("package_module")).resolve()
        row["request_sha256"] = hashlib.sha256(row.pop("request_json").encode()).hexdigest()
        if args.check:
            assert row["failure"] is None, row
            assert row["raw_contacts_sent"] == [], row
            assert row["restored_text"] == EXPECTED_TEXT, row
            assert row["input_unchanged"] and row["iterator_visited_once"], row
            assert row["citations_unchanged"] and row["vault_entries"] == 4, row
            assert row["attribution_restores"], row
        # Keep one full request per placement/mode, all other digests and checks.
        if shape != "list" or asynchronous:
            row.pop("requests")
        rows.append(row)
    assert package_path is not None
    origin = (
        "selected-source"
        if args.source and package_path.is_relative_to(args.source.resolve())
        else "environment"
        if package_path.is_relative_to(Path(sys.prefix).resolve())
        else "outside-environment"
    )
    receipt = {
        "label": args.label or ("source" if args.source else "installed"),
        "package_origin": origin,
        "package_python_sha256": {
            str(path.relative_to(package_path.parent)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(package_path.parent.rglob("*.py"))
        },
        "python": platform.python_version(),
        "anthropic": anthropic.__version__,
        "workflow_count": len(rows),
        "requests_with_raw_contacts": sum(bool(row["raw_contacts_sent"]) for row in rows),
        "workflows_with_unchanged_citations": sum(row["citations_unchanged"] for row in rows),
        "workflows_with_restored_answers": sum(
            row["restored_text"] == EXPECTED_TEXT for row in rows
        ),
        "workflows_with_failures": sum(row["failure"] is not None for row in rows),
        "rows": rows,
    }
    if args.summary:
        for key, value in receipt.items():
            if key not in ("rows", "package_python_sha256"):
                print(f"{key}: {value}")
        print("Controlled synthetic contacts and replies; real SDK; mock HTTP only.")
    else:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
