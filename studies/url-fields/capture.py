# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx2==2.13.1"]
# ///
"""Capture actual HTTPX2/urllib URLs against an authored loopback credential check."""

from __future__ import annotations

import json
import platform
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import httpx2

HERE = Path(__file__).resolve().parent
VALUES = {
    "client_secret": "short&local=proof",
    "refresh_token": "retry-word",
    "passwd": "wordlike",
    "SERVICE_PASSWORD": "localpass",
}
received: list[dict[str, object]] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parameters = parse_qs(urlsplit(self.path).query)
        accepted = len(parameters) == 1 and any(
            parameters == {key: [value]} for key, value in VALUES.items()
        )
        received.append({"target": self.path, "accepted": accepted})
        self.send_response(200 if accepted else 401)
        self.end_headers()
        self.wfile.write(b"accepted local control" if accepted else b"incorrect local control")

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/request"
    rows = []
    try:
        with httpx2.Client(trust_env=False) as client:
            opener = build_opener(ProxyHandler({}))
            for producer in ["httpx2", "urllib"]:
                for field, expected in VALUES.items():
                    for correct in [True, False]:
                        value = expected if correct else "incorrect"
                        if producer == "httpx2":
                            request = client.build_request("GET", endpoint, params={field: value})
                            source = str(request.url)
                            status = client.send(request).status_code
                        else:
                            request2 = Request(endpoint + "?" + urlencode({field: value}))
                            source = request2.full_url
                            try:
                                with opener.open(request2) as response:
                                    status = response.status
                            except HTTPError as error:
                                status = error.code
                                error.close()
                        assert status == (200 if correct else 401)
                        assert received[-1]["target"] == "/request?" + source.partition("?")[2]
                        rows.append(
                            {
                                "producer": producer,
                                "field": field,
                                "url": source,
                                "accepted": correct,
                                "status": status,
                            }
                        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert len(received) == 16 and sum(bool(row["accepted"]) for row in received) == 8
    receipt = {
        "scope": __doc__,
        "python": platform.python_version(),
        "httpx2": version("httpx2"),
        "credentials": "Authored controls valid only for the temporary loopback server. No external account or provider is involved.",
        "cases": rows,
        "received": received,
    }
    (HERE / "capture.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"actualRequests": len(rows), "acceptedControls": 8, "refusedControls": 8}))


if __name__ == "__main__":
    main()
