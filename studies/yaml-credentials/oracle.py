"""Differential YAML recognition matrix, using two independent native parsers.

uv run --locked --with PyYAML==6.0.3 --with ruamel.yaml==0.18.16 \
  python studies/yaml-credentials/oracle.py --output /tmp/yaml-oracle.json
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError as OtherYAMLError

from veil import Masker
from veil.detectors import _credential_fields


def at_path(tree, path):
    for key in path:
        tree = tree[key]
    return tree


def matrix():
    indicators = ["", "-", "+"]
    for digit in "123456789":
        indicators += [digit, digit + "-", "-" + digit, digit + "+", "+" + digit]
    contexts = [
        ("root", "", "", ["password"]),
        ("mapping", "connection:\n", "  ", ["connection", "password"]),
        ("sequence", "connections:\n", "- ", ["connections", 0, "password"]),
        ("compact", "connections:\n", "  - - ", ["connections", 0, 0, "password"]),
    ]
    bodies = {
        "ordinary": ["river", "stone"],
        "blank": ["", "river", "", "stone", ""],
        "comment": ["# river", "api_key=stone"],
        "indented": ["   river", " stone"],
        "tab": ["\triver", "\tstone"],
        "unicode": ["river", "石の上にも三年", "stone"],
    }
    for style, flags, context, body, newline in itertools.product(
        ("|", ">"),
        indicators,
        contexts,
        bodies,
        ("\n", "\r\n", "\r"),
    ):
        name, preamble, prefix, path = context
        digit = next((int(c) for c in flags if c.isdigit()), 2)
        indent = len(prefix) + digit
        # A leading space is content only with an explicit indentation digit.
        # Otherwise the first line determines the automatic indentation level.
        payload = bodies[body]
        if body == "indented" and not any(c.isdigit() for c in flags):
            payload = ["river", "   stone"]
        if body == "tab" and not any(c.isdigit() for c in flags):
            # LibYAML rejects a leading tab under automatic indentation, while
            # PyYAML's Python loader accepts it. Keep this shared-valid matrix
            # to tabs inside content or after an explicit indentation digit.
            payload = ["river\tmeadow", "stone\tvalley"]
        source = (
            preamble
            + f"{prefix}password: {style}{flags} # diagnostic header\n"
            + "".join(" " * indent + line + "\n" if line else "\n" for line in payload)
            + " " * len(prefix)
            + "mode: read-only\nstatus: failed\n"
        ).replace("\n", newline)
        yield {
            "id": f"{style}{flags}:{name}:{body}:{repr(newline)}",
            "style": style,
            "context": name,
            "body": body,
            "line_break": repr(newline),
            "source": source,
            "path": path,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    other = YAML(typ="safe")
    inputs = hashlib.sha256()
    counts = Counter()
    breakdown = {key: {} for key in ("style", "context", "body", "line_break")}
    examples = []
    for case in matrix():
        inputs.update(json.dumps(case, sort_keys=True, ensure_ascii=False).encode() + b"\n")
        source = case["source"]
        original = yaml.safe_load(source)
        assert other.load(source) == original, case["id"]
        masker = Masker()
        masked = masker.mask(source)
        assert masker.restore(masked, tolerant=False) == source
        counts["cases"] += 1
        safe = "river" not in masked and "stone" not in masked
        counts["protected"] += safe
        try:
            parsed = yaml.safe_load(masked)
            assert other.load(masked) == parsed, case["id"]
        except (yaml.YAMLError, OtherYAMLError):
            # Old literal-marker masking can also make valid YAML invalid.
            # Retain that outcome; a baseline parse failure is not protection.
            if safe:
                raise
            parsed = None
            counts["masked_parse_errors"] += 1
        else:
            counts["two_parsers_agree_on_both_documents"] += 1
        counts["exact_restore"] += 1
        if safe:
            value = at_path(parsed, case["path"])
            assert value.strip() == "⟨SECRET_1⟩", (case["id"], value)
            parent = at_path(original, case["path"][:-1])
            parent[case["path"][-1]] = value
            assert original == parsed, case["id"]
            assert len(masker.vault) == 1
            counts["only_credential_value_changed"] += 1
        for key in breakdown:
            item = breakdown[key].setdefault(case[key], {"cases": 0, "protected": 0})
            item["cases"] += 1
            item["protected"] += safe
        if len(examples) < 6 or (not safe and len(examples) < 12):
            examples.append(
                {"id": case["id"], "source": source, "masked": masked, "protected": safe}
            )
    result = {
        "inputs_sha256": inputs.hexdigest(),
        "runtime_sha256": hashlib.sha256(
            Path(_credential_fields.__file__).read_bytes()
        ).hexdigest(),
        "parsers": {name: version(name) for name in ("PyYAML", "ruamel.yaml")},
        "synthetic": True,
        "counts": dict(counts),
        "breakdown": breakdown,
        "examples": examples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result["counts"]))
    if args.require_fixed:
        assert counts["protected"] == counts["cases"]


if __name__ == "__main__":
    main()
