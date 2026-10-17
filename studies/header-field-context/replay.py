"""Measure original-value masking through real SDK serialization and echo streams."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import runpy
import sys
from importlib.metadata import version
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observe-only", action="store_true")
    args = parser.parse_args()
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import openai

    import veil
    from veil import Masker
    from veil.backends import KnownEntitiesBackend
    from veil.integrations._json_arguments import mask_string_value

    sys.path.insert(0, str(ROOT))
    from tests.sdk_wire import http_module

    package = Path(veil.__file__).resolve().parent
    assert package.is_relative_to(args.src.resolve() if args.src else Path(sys.prefix).resolve())
    capture = runpy.run_path(str(HERE.parent / "http-authorization/sdk_tools.py"))[
        "sdk_tool_capture"
    ]
    # These are generated locally from invented credentials; no authentication occurs.
    http = http_module(openai)
    request = http.Request("GET", "https://example.invalid/")
    basic = next(http.BasicAuth("customer-17", "correct horse").auth_flow(request)).headers[
        "Authorization"
    ]
    rows = []
    for key in ["Authorization", "authorization", "Proxy-Authorization"]:
        for value in ["Bearer abc", basic]:
            masker = Masker(name_backends=[KnownEntitiesBackend(orgs=["Authorization:"])])
            masked = mask_string_value(value, masker, key=key)
            credential = value.split(" ", 1)[1]
            expected = value.replace(credential, "⟨SECRET_1⟩")
            rows.append(
                {
                    "key": key,
                    "source": value,
                    "masked": masked,
                    "expected": expected,
                    "restored": masker.restore(masked),
                    "correct": masked == expected and masker.restore(masked) == value,
                    "vault": json.loads(masker.vault.to_json()),
                }
            )
    source = '{ "headers":{"Authorization":"Bearer abc"}, "count":1.2300e+40 }'
    expected = source.replace("Bearer abc", "Bearer ⟨SECRET_1⟩")
    sdk_rows = []
    for api in ["chat", "responses", "anthropic"]:
        for asynchronous in [False, True]:
            for streaming in [False, True]:
                for tool_reply in [False, True]:
                    masker = Masker(name_backends=[KnownEntitiesBackend(orgs=["Authorization:"])])
                    result = capture(
                        api,
                        asynchronous,
                        streaming,
                        source=source,
                        expected=expected,
                        tool_reply=tool_reply,
                        masker=masker,
                        assert_roundtrip=False,
                    )
                    sdk_rows.append(
                        result
                        | {"toolReply": tool_reply, "vault": json.loads(masker.vault.to_json())}
                    )
    failures = sum(not row["correct"] for row in rows)
    sdk_failures = sum(not (row["correct"] and row["restoresExactly"]) for row in sdk_rows)
    output = {
        "scope": (
            "Controlled configured name backend; real SDKs with mock HTTP transports, "
            "buffered/one-character echo streams. No provider/model or authentication calls."
        ),
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ["veil-pii", "openai", "anthropic"]},
        "source_sha256": {
            str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(package.rglob("*.py"))
        },
        "native_auth_http_module": http.__name__,
        "native_auth_header": basic,
        "direct_failures": failures,
        "sdk_failures": sdk_failures,
        "direct": rows,
        "sdk": sdk_rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"6 direct / 24 SDK paths: {failures} / {sdk_failures} unexpected results")
    if not args.observe_only:
        assert failures + sdk_failures == 0
        for row in rows + sdk_rows:
            assert len(row["vault"]["mappings"]) == 1
            assert row["vault"]["mappings"][0]["type"] == "SECRET"


if __name__ == "__main__":
    main()
