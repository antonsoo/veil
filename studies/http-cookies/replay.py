"""Replay native local cookie observations through masking, CLI and SDK transport."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import runpy
import subprocess
import sys
import tempfile
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observe-only", action="store_true")
    parser.add_argument("--sdk", action="store_true")
    args = parser.parse_args()
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import veil
    from veil import Masker, Restorer

    package = Path(veil.__file__).resolve().parent
    assert package.is_relative_to(args.src.resolve() if args.src else Path(sys.prefix).resolve())
    oracle = json.loads((HERE / "fixtures/oracle.json").read_text())
    for record in oracle["files"]:
        assert (
            hashlib.sha256((HERE / "fixtures" / record["file"]).read_bytes()).hexdigest()
            == record["sha256"]
        )
    rows = []
    with tempfile.TemporaryDirectory(prefix="veil-cookie-cli-") as directory:
        for record in oracle["files"]:
            source = (HERE / "fixtures" / record["file"]).read_text()
            masker = Masker()
            masked = masker.mask(source)
            restored = masker.restore(masked, tolerant=False)
            assert masker.restore(masked) == restored == source
            restorer = Restorer(masker.vault)
            assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source
            vault = Path(directory) / (record["file"] + ".vault.json")
            call = subprocess.run(
                [sys.executable, "-m", "veil.cli", "mask", "--vault", str(vault)],
                input=source,
                text=True,
                capture_output=True,
                check=True,
                env={**os.environ, "PYTHONPATH": str(package.parent)},
            )
            assert call.stdout == masked
            undo = subprocess.run(
                [sys.executable, "-m", "veil.cli", "restore", "--exact", "--vault", str(vault)],
                input=masked,
                text=True,
                capture_output=True,
                check=True,
                env={**os.environ, "PYTHONPATH": str(package.parent)},
            )
            assert undo.stdout == source
            rows.append(
                {
                    "file": record["file"],
                    "masked": masked,
                    "restoresExactly": True,
                    "streamRestoresExactly": True,
                    "cliMatches": True,
                    "sessionAbsent": oracle["session"] not in masked,
                    "vault": json.loads(masker.vault.to_json()),
                }
            )

    # A new local server deliberately recognizes only the retained synthetic
    # session. This is a controlled replay, separate from the closed capture.
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def do_GET(self) -> None:
            cookies: SimpleCookie[str] = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            accepted = "sid" in cookies and cookies["sid"].value == oracle["session"]
            self.send_response(200 if accepted else 401)
            self.end_headers()

    masker = Masker()
    masked = masker.mask(oracle["cookie"], field_name="Cookie")
    candidates = {
        "original": oracle["cookie"],
        "masked": masked,
        "restored": masker.restore(masked),
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    statuses = {}
    try:
        for name, value in candidates.items():
            client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                # Placeholder bytes are UTF-8 only for this rejection control;
                # masking for an LLM is not a usable HTTP credential generator.
                client.request("GET", "/private", headers={"Cookie": value.encode("utf-8")})
                response = client.getresponse()
                statuses[name] = response.status
                response.read()
            finally:
                client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert statuses["original"] == statuses["restored"] == 200
    sdk = []
    if args.sdk:
        capture = runpy.run_path(str(HERE.parent / "http-authorization/sdk_tools.py"))[
            "sdk_tool_capture"
        ]
        source = (HERE / "fixtures/request-headers.json").read_text().rstrip("\n")
        expected = source.replace(oracle["cookie"], "\\u27e8SECRET_1\\u27e9")
        for api in ["chat", "responses", "anthropic"]:
            for asynchronous in [False, True]:
                for streaming in [False, True]:
                    for tool_reply in [False, True]:
                        result = capture(
                            api,
                            asynchronous,
                            streaming,
                            source=source,
                            expected=expected,
                            tool_reply=tool_reply,
                            assert_roundtrip=False,
                        )
                        sdk.append(result | {"toolReply": tool_reply})
    failures = sum(not row["sessionAbsent"] for row in rows) + (statuses["masked"] != 401)
    sdk_failures = sum(not (row["correct"] and row["restoresExactly"]) for row in sdk)
    result = {
        "scope": "Retained native loopback exchange plus separately controlled loopback authentication replay. SDKs use mock transports; no provider or model call. Masked placeholder rejection uses UTF-8 header bytes, not a claim of HTTP-valid surrogate credentials.",
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ["veil-pii", "openai", "anthropic"]},
        "oracleSha256": hashlib.sha256((HERE / "fixtures/oracle.json").read_bytes()).hexdigest(),
        "sourceHashes": {
            str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(package.rglob("*.py"))
        },
        "direct": rows,
        "controlledAuthenticationStatus": statuses,
        "sdk": sdk,
        "directFailures": failures,
        "sdkFailures": sdk_failures,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        f"3 native header forms + loopback replay + {len(sdk)} SDK paths: {failures} / {sdk_failures} failures"
    )
    if not args.observe_only:
        assert failures == sdk_failures == 0


if __name__ == "__main__":
    main()
