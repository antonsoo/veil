"""Retain actual default/quoted PyYAML/ruamel.yaml emissions, with independent loaders.

Study dependencies only; no YAML dependency is added to Veil.
"""

from __future__ import annotations

import hashlib
import json
from io import StringIO
from pathlib import Path

import yaml
from ruamel.yaml import YAML
from ruamel.yaml import __version__ as ruamel_version
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString

HERE = Path(__file__).resolve().parent
VALUES = {
    "apostrophe": "sun'rise",
    "two-apostrophes": "sun''rise",
    "backslash": "river\\",
    "wrapped": "river stone quiet meadow",
    "line-break": "river\nstone",
    "blank-line": "river\n\nstone",
    "assignment": "river api_key=stone quiet meadow",
    "nested-pii": "river help@example.org 4111 1111 1111 1111 stone",
    "unicode": "river 石の上にも三年 stone",
    "quotes": "river 'quiet' \"stone\" meadow",
}


def capture() -> dict:
    rows = []
    for writer in ("pyyaml", "ruamel"):
        for style in (None, "'", '"'):
            for context in ("mapping", "sequence"):
                for name, value in VALUES.items():
                    if writer == "pyyaml":

                        class Quoted(str):
                            pass

                        class Dumper(yaml.SafeDumper):
                            pass

                        Dumper.add_representer(
                            Quoted,
                            lambda d, v, style=style: d.represent_scalar(
                                "tag:yaml.org,2002:str", str(v), style=style
                            ),
                        )
                        wrapped = Quoted(value)
                    else:
                        scalar = (
                            SingleQuotedScalarString if style == "'" else DoubleQuotedScalarString
                        )
                        wrapped = value if style is None else scalar(value)
                    data = (
                        {
                            "connection": {"password": wrapped, "mode": "read-only"},
                            "status": "failed",
                        }
                        if context == "mapping"
                        else {
                            "connections": [{"client_secret": wrapped, "mode": "read-only"}],
                            "status": "failed",
                        }
                    )
                    if writer == "pyyaml":
                        source = yaml.dump(
                            data, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=16
                        )
                    else:
                        output = StringIO()
                        native = YAML()
                        native.width = 16
                        native.dump(data, output)
                        source = output.getvalue()
                    parsed = yaml.safe_load(source)
                    assert YAML(typ="safe").load(source) == parsed
                    path = (
                        ["connection", "password"]
                        if context == "mapping"
                        else ["connections", 0, "client_secret"]
                    )
                    actual = parsed
                    for key in path:
                        actual = actual[key]
                    assert actual == value
                    tokens = [
                        token
                        for token in yaml.scan(source)
                        if isinstance(token, yaml.tokens.ScalarToken) and token.value == value
                    ]
                    assert len(tokens) == 1
                    token = tokens[0]
                    quoted = token.style in ("'", '"')
                    start, end = (
                        token.start_mark.index + int(quoted),
                        token.end_mark.index - int(quoted),
                    )
                    if quoted:
                        assert source[start - 1] == source[end] == token.style
                    rows.append(
                        {
                            "id": f"{writer}-{'default' if style is None else 'single' if style == chr(39) else 'double'}-{context}-{name}",
                            "source": source,
                            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                            "credential_path": path,
                            "decoded_original": value,
                            "emitted_style": token.style,
                            "raw_body": source[start:end],
                            "native_body_span": [start, end],
                            "expected_masked": source[:start] + "⟨SECRET_1⟩" + source[end:],
                        }
                    )
    return {
        "synthetic": True,
        "writers": {
            "PyYAML": yaml.__version__,
            "ruamel.yaml": ruamel_version,
        },
        "cases": rows,
    }


if __name__ == "__main__":
    target = HERE / "fixtures/native.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    result = capture()
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Retained {len(result['cases'])} actual native emissions; both loaders agree.")
