"""Emit controlled YAML with the real PyYAML writer; keep a parser oracle.

uv run --locked --with PyYAML==6.0.3 python studies/yaml-credentials/capture.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


class Block(str):
    pass


def cases() -> list[dict]:
    rows = []
    for style in ("|", ">"):

        class Dumper(yaml.SafeDumper):
            pass

        Dumper.add_representer(
            Block,
            lambda d, value, style=style: d.represent_scalar(
                "tag:yaml.org,2002:str", str(value), style=style
            ),
        )
        for name, value in (
            ("ordinary", "river\nstone\n"),
            ("strip", "river\nstone"),
            ("keep", "river\nstone\n\n"),
            ("leading", "\nriver\nstone\n"),
            ("indent", "  river\n stone\n"),
            ("nested", "river\napi_key=stone\n# not a YAML comment\n"),
            ("pii", "river\nhelp@example.org\n4111 1111 1111 1111\nstone\n"),
            ("unicode", "river\n石の上にも三年\nstone\n"),
        ):
            source = yaml.dump(
                {
                    "connection": {"password": Block(value), "mode": "read-only"},
                    "status": "failed",
                },
                Dumper=Dumper,
                sort_keys=False,
                allow_unicode=True,
            )
            assert yaml.safe_load(source)["connection"]["password"] == value
            tokens = [t for t in yaml.scan(source) if getattr(t, "style", None) == style]
            assert len(tokens) == 1 and tokens[0].value == value
            token = tokens[0]
            rows.append(
                {
                    "id": f"native-{'literal' if style == '|' else 'folded'}-{name}",
                    "kind": "native-pyyaml-emission",
                    "source": source,
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "credential_path": ["connection", "password"],
                    "decoded_original": value,
                    "native_scalar_span": [token.start_mark.index, token.end_mark.index],
                    "header": source[
                        token.start_mark.index : source.index("\n", token.start_mark.index)
                    ],
                    "sensitive_fragments": ["river", "stone"],
                    "retained_fragments": [
                        "connection:",
                        "  mode: read-only\n",
                        "status: failed\n",
                    ],
                }
            )
    return rows


if __name__ == "__main__":
    HERE.joinpath("fixtures").mkdir(exist_ok=True)
    rows = cases()
    HERE.joinpath("fixtures/native.json").write_text(
        json.dumps(
            {"writer": f"PyYAML {yaml.__version__}", "synthetic": True, "cases": rows},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    print(f"Retained {len(rows)} actual writer outputs with native parser/token checks.")
