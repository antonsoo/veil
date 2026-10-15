"""Capture native HTTP Basic headers, masking, CLI vaults and SDK transport.

All credentials are synthetic. HTTPX and the model SDKs use MockTransport;
no network requests, real accounts or provider API keys are needed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import runpy
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

from veil import Masker, Restorer
from veil.detectors import secrets as secrets_module

HERE = Path(__file__).resolve().parent


def native_cases() -> list[dict[str, Any]]:
    import httpx

    cases = []
    for name, username, password in (
        ("short", "user", "pass"),
        ("empty-user", "", "p"),
        ("empty-password", "service", ""),
        ("colon-password", "worker", "first:second"),
        ("long-password", "customer-17", "correct horse battery staple"),
        ("unicode", "\u00fcser", "p\u00e4ssw\u00f6rd"),
        ("contact", "alice@example.com", "secret"),
    ):
        captured = []

        def record(request: httpx.Request, captured: list[str] = captured) -> httpx.Response:
            captured.append(request.headers["authorization"])
            return httpx.Response(200)

        with httpx.Client(
            auth=(username, password), transport=httpx.MockTransport(record)
        ) as client:
            client.get("https://synthetic.invalid/private")
        assert len(captured) == 1
        header = captured[0]
        credential = header.split(" ", 1)[1]
        assert base64.b64decode(credential, validate=True) == f"{username}:{password}".encode()
        cases.append(
            {
                "id": f"httpx-{name}",
                "source": f"Authorization: {header}\r\n",
                "token": credential,
                "expected": "Authorization: Basic \u27e8SECRET_1\u27e9\r\n",
                "producer": "httpx.BasicAuth over MockTransport; stdlib Base64 decoding checked",
            }
        )
    for name, source, token, expected in (
        (
            "bearer-short",
            "Authorization: Bearer abc\r\n",
            "abc",
            "Authorization: Bearer \u27e8SECRET_1\u27e9\r\n",
        ),
        (
            "bearer-hex",
            "Authorization: Bearer aabbccddeeff0011",
            "aabbccddeeff0011",
            "Authorization: Bearer \u27e8SECRET_1\u27e9",
        ),
        (
            "bearer-token68",
            "Authorization: Bearer ab.c_d-ef~g+/==",
            "ab.c_d-ef~g+/==",
            "Authorization: Bearer \u27e8SECRET_1\u27e9",
        ),
        (
            "proxy",
            "Proxy-Authorization: Basic dXNlcjpwYXNz",
            "dXNlcjpwYXNz",
            "Proxy-Authorization: Basic \u27e8SECRET_1\u27e9",
        ),
        (
            "json",
            '{"authorization": "Bearer abc"}',
            "abc",
            '{"authorization": "Bearer \u27e8SECRET_1\u27e9"}',
        ),
        (
            "curl",
            "curl -H 'Authorization: Basic dXNlcjpwYXNz' https://example.org/",
            "dXNlcjpwYXNz",
            "curl -H 'Authorization: Basic \u27e8SECRET_1\u27e9' https://example.org/",
        ),
        (
            "mixed-case",
            "aUtHoRiZaTiOn:\t bEaReR\txyz",
            "xyz",
            "aUtHoRiZaTiOn:\t bEaReR\t\u27e8SECRET_1\u27e9",
        ),
    ):
        cases.append(
            {
                "id": name,
                "source": source,
                "token": token,
                "expected": expected,
                "producer": "Constructed header/log spelling; not an issued credential",
            }
        )
    for case in cases:
        if not case["source"].endswith("\n"):
            case["source"] += "\n"
            case["expected"] += "\n"
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sdk", action="store_true")
    parser.add_argument(
        "--native", action="store_true", help="Recheck retained fixtures with HTTPX BasicAuth"
    )
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    if args.native:
        assert native_cases() == cases
    rows = []
    with tempfile.TemporaryDirectory(prefix="veil-http-authorization-") as directory:
        for case in cases:
            masker = Masker()
            source = case["source"]
            masked = masker.mask(source)
            assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
            for size in (1, 2, 7, 31):
                restorer = Restorer(masker.vault)
                reply = "".join(
                    restorer.feed(masked[i : i + size]) for i in range(0, len(masked), size)
                )
                assert reply + restorer.flush() == source
            vault = Path(directory) / f"{case['id']}.json"
            cli = subprocess.run(
                [sys.executable, "-m", "veil.cli", "mask", "--vault", str(vault)],
                input=source.encode(),
                capture_output=True,
                check=True,
            )
            assert not cli.stderr and cli.stdout.decode() == masked
            restored = subprocess.run(
                [sys.executable, "-m", "veil.cli", "restore", "--exact", "--vault", str(vault)],
                input=cli.stdout,
                capture_output=True,
                check=True,
            )
            assert not restored.stderr and restored.stdout == source.encode()
            rows.append(
                {
                    **case,
                    "masked": masked,
                    "correct": masked == case["expected"],
                    "wholeCredentialInVault": any(
                        m.original == case["token"] for m in masker.vault.mappings()
                    ),
                    "credentialStillVisible": case["token"] in masked,
                    "exactCLIAndStreamRestore": True,
                    "streamChunkSizes": [1, 2, 7, 31],
                }
            )
    captures = []
    tools = []
    if args.sdk:
        capture = runpy.run_path(str(HERE.parent / "email-boundaries/replay.py"))["sdk_capture"]
        # Different repeated native headers should retain one shared surrogate.
        source = "\n".join(case["source"].rstrip("\r\n") for case in cases)
        tokens = list(dict.fromkeys(case["token"] for case in cases))
        replacements = {
            token: f"\u27e8SECRET_{index}\u27e9" for index, token in enumerate(tokens, 1)
        }
        expected = "\n".join(
            case["source"].rstrip("\r\n").replace(case["token"], replacements[case["token"]])
            for case in cases
        )
        for api in ("chat", "responses", "anthropic"):
            for asynchronous in (False, True):
                for streaming in (False, True):
                    row = capture(source, api, asynchronous, streaming)
                    row["correct"] = row["outgoing"] == expected
                    captures.append(row)
        capture_tool = runpy.run_path(str(HERE / "sdk_tools.py"))["sdk_tool_capture"]
        tools = [
            capture_tool(api, asynchronous, streaming)
            for api in ("chat", "responses", "anthropic")
            for asynchronous in (False, True)
            for streaming in (False, True)
        ]
    helper = Path(secrets_module.__file__).with_name("_http_auth.py")
    package_root = Path(secrets_module.__file__).parents[1]
    report = {
        "provenance": "Synthetic credentials only. Native HTTPX BasicAuth and SDK serializers over mock HTTP; no live provider/account requests.",
        "python": sys.version.split()[0],
        "versions": {
            name: version(name)
            for name in (
                ("httpx", "openai", "anthropic") if args.sdk else ("httpx",) if args.native else ()
            )
        },
        "nativeHeaderCaptureChecked": args.native,
        "sourceSha256": hashlib.sha256(Path(secrets_module.__file__).read_bytes()).hexdigest(),
        "authSourceSha256": hashlib.sha256(helper.read_bytes()).hexdigest()
        if helper.exists()
        else None,
        "runtimeFiles": {
            str(path.relative_to(package_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package_root.rglob("*"))
            if path.is_file() and (path.suffix == ".py" or path.name == "py.typed")
        },
        "cases": rows,
        "sdk": captures,
        "sdkTools": tools,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{sum(row['correct'] for row in rows)}/{len(rows)} complete credentials; {sum(row['correct'] for row in captures)}/{len(captures)} SDK text requests; {sum(row['correct'] for row in tools)}/{len(tools)} SDK tool requests; exact CLI/stream restoration retained"
    )
    if args.require_fixed:
        assert all(row["correct"] and row["wholeCredentialInVault"] for row in rows)
        assert all(row["correct"] for row in captures)
        assert all(row["correct"] and row["unrelatedSyntaxPreserved"] for row in tools)


if __name__ == "__main__":
    main()
