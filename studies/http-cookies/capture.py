"""Retain a native stdlib cookie-jar exchange against an ephemeral loopback server.

All credentials are local and synthetic. The session is valid only while this
process runs. No external request, model or provider is involved.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import platform
import secrets
import threading
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    token = secrets.token_hex(16)
    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def do_GET(self) -> None:
            if self.path == "/login":
                self.send_response(200)
                self.send_header("Set-Cookie", f"sid={token}; HttpOnly; Path=/; SameSite=Lax")
                self.send_header("Set-Cookie", "theme=dark; Path=/")
                self.end_headers()
                return
            cookie = self.headers.get("Cookie", "")
            values: SimpleCookie[str] = SimpleCookie()
            values.load(cookie)
            valid = "sid" in values and values["sid"].value == token
            captured["requestHeaders"] = str(self.headers)
            captured["cookie"] = cookie
            self.send_response(200 if valid else 401)
            self.end_headers()
            self.wfile.write(b"local private document" if valid else b"unauthorized")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with opener.open(base + "/login", timeout=5) as response:
            response_headers = str(response.headers)
            set_cookies = response.headers.get_all("Set-Cookie")
        with opener.open(base + "/private", timeout=5) as response:
            status, body = response.status, response.read().decode()
        assert status == 200 and token in str(captured["cookie"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    args.out.mkdir(parents=True, exist_ok=False)
    files = {
        "request-headers.txt": str(captured["requestHeaders"]),
        "response-headers.txt": response_headers,
        "request-headers.json": json.dumps({"headers": {"Cookie": captured["cookie"]}}) + "\n",
    }
    for name, source in files.items():
        (args.out / name).write_text(source)
    oracle = {
        "scope": "Real stdlib HTTP response and CookieJar request on loopback; local synthetic session, server closed after capture.",
        "python": platform.python_version(),
        "captureSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "session": token,
        "cookie": captured["cookie"],
        "setCookies": set_cookies,
        "authenticated": {"status": status, "body": body},
        "files": [
            {"file": name, "sha256": hashlib.sha256((args.out / name).read_bytes()).hexdigest()}
            for name in files
        ],
    }
    (args.out / "oracle.json").write_text(json.dumps(oracle, indent=2) + "\n")
    print("Retained native CookieJar request and two distinct Set-Cookie fields")


if __name__ == "__main__":
    main()
