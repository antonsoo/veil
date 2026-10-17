"""Check supported flow-scalar mapping syntax with independent YAML loaders."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import yaml
from ruamel.yaml import YAML
from ruamel.yaml import __version__ as ruamel_version
from ruamel.yaml.error import YAMLError as RuamelError

from veil import Masker
from veil.detectors import _credential_fields

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--require-fixed", action="store_true")
args = parser.parse_args()
loader = YAML(typ="safe")
rows = []
ledger = hashlib.sha256()
for style, context, key, newline, body_name, final, delayed in itertools.product(
    ("'", '"', ""),
    ("root", "nested", "sequence", "compact"),
    ("password", "'client_secret'", '"SERVICE_PASSWORD"'),
    ("\n", "\r\n", "\r"),
    ("apostrophe", "backslash", "wrapped", "blank", "block-looking"),
    (True, False),
    (True, False),
):
    prefix, indent = {
        "root": ("", "  "),
        "nested": ("connection:\n  ", "    "),
        "sequence": ("- ", "    "),
        "compact": ("- - ", "      "),
    }[context]
    body = {
        "apostrophe": "sun''rise" if style == "'" else "sun'rise",
        "backslash": "river\\\\" if style == '"' else "river\\",
        "wrapped": "river\n" + indent + "stone",
        "blank": "river\n\n" + indent + "stone",
        "block-looking": "river\n"
        + indent
        + ("api_key: |" if style else "api_key:|-")
        + "\n"
        + indent
        + "  quiet",
    }[body_name]
    separator = "\n" + indent if delayed else " "
    source = "\ufeff" + prefix + f"{key}:{separator}{style}{body}{style} # diagnostic"
    source += "\n" if final else ""
    source = source.replace("\n", newline)
    before = yaml.safe_load(source)
    assert loader.load(source) == before
    ledger.update(source.encode())
    masker = Masker()
    masked = masker.mask(source)
    assert masker.restore(masked, tolerant=False) == source
    expected = source.replace(body.replace("\n", newline), "⟨SECRET_1⟩", 1)
    protected = masked == expected
    parse_ok = False
    try:
        after = yaml.safe_load(masked)
        parse_ok = loader.load(masked) == after
    except (yaml.YAMLError, RuamelError):
        pass
    # No other mapping, sequence, key or comment should change. The expected
    # source contains exactly one replacement at the known constructed body.
    rows.append(
        {
            "id": [style, context, key, repr(newline), body_name, final, delayed],
            "protected": protected,
            "masked_loaders_agree": parse_ok,
        }
    )
failures = [r for r in rows if not r["protected"] or not r["masked_loaders_agree"]]
examples = {}
for failure in failures:
    examples.setdefault(tuple(failure["id"][:2]), failure)
result = {
    "synthetic": True,
    "cases": len(rows),
    "protected": sum(r["protected"] for r in rows),
    "masked_parse_failures": sum(not r["masked_loaders_agree"] for r in rows),
    "input_ledger_sha256": ledger.hexdigest(),
    "runtime_sha256": hashlib.sha256(Path(_credential_fields.__file__).read_bytes()).hexdigest(),
    "loaders": {
        "PyYAML": yaml.__version__,
        "ruamel.yaml": ruamel_version,
    },
    "failure_count": len(failures),
    "failure_ledger_sha256": hashlib.sha256(json.dumps(failures).encode()).hexdigest(),
    "failure_examples_by_style_and_context": list(examples.values()),
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k: result[k] for k in ("cases", "protected", "masked_parse_failures")}))
if args.require_fixed:
    assert result["protected"] == len(rows) and result["masked_parse_failures"] == 0
