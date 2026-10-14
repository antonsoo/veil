"""Capture actual OpenAI SDK serialization of synthetic iterable inline text."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, help="omit for an installed wheel")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observe-only", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))  # Independent SDK fixtures, not product source.
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import veil
    from tests.sdk_iterable_text import KINDS, MODES, SHAPES, capture

    origin = Path(veil.__file__).resolve()
    if args.src:
        assert origin.is_relative_to(args.src.resolve())
    else:
        assert "site-packages" in origin.parts, "Use --src for a source installation"

    cases = [capture(*p) for p in product(KINDS, SHAPES, [False, True], MODES)]
    cases += [
        capture(kind, shape, asynchronous, "complete", collision=True)
        for kind, shape, asynchronous in product(
            ["chat-text", "response-content", "response-input"], SHAPES, [False, True]
        )
    ]
    for case in cases:
        if case["collision"]:
            case["agrees"] = (
                case["failure"] is not None
                and case["failure"]["type"] == "VaultError"
                and not case["requests"]
                and case["vaultEntriesAfter"] == 0
            )
        else:
            case["agrees"] = (
                case["failure"] is None
                and len(case["requests"]) == 1
                and not case["recognizedRawContactSent"]
                and case["vaultEntriesAfter"] == 1
            )
    source = origin.parent / "integrations"
    result = {
        "python": sys.version.split()[0],
        "openai": importlib.metadata.version("openai"),
        "runtimeSourceSha256": {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in ["openai.py", "openai_responses.py"]
        },
        "population": "Synthetic contacts and controlled replies over real SDK/mock HTTP. No live API acceptance or inference. Responses top-level generators were rejected by the baseline SDK and are a newly materialized input, not a baseline privacy leak.",
        "count": len(cases),
        "disagreements": sum(not case["agrees"] for case in cases),
        "requestsWithRawContact": sum(case["recognizedRawContactSent"] for case in cases),
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=2))
    if result["disagreements"] and not args.observe_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
