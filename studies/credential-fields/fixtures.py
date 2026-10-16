"""Synthetic credential assignments, produced locally; never issued secrets."""

from __future__ import annotations

import configparser
import io
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cases() -> list[dict]:
    rows = []

    def add(
        name: str, source: str, value: str | None, producer: str = "constructed spelling"
    ) -> None:
        start = source.rfind(value) if value is not None else -1
        assert value is None or start >= 0
        rows.append(
            {
                "id": name,
                "source": source,
                "value": value,
                "expected": source
                if value is None
                else source[:start] + "⟨SECRET_1⟩" + source[start + len(value) :],
                "producer": producer,
            }
        )

    for key, value in (
        ("password", "correct-horse"),
        ("passwd", "a"),
        ("api_key", "short-token"),
        ("apiKey", "deadbeef"),
        ("client_secret", "river stone"),
        ("clientSecret", "密钥🔑"),
        ("access_token", "session-token"),
        ("refresh_token", "next-session"),
        ("refreshToken", "short/+=token"),
    ):
        add(f"json-{key}", json.dumps({key: value}, ensure_ascii=False), value, "stdlib json.dumps")
    for name, source, value in (
        ("env", "API_KEY=local-key", "local-key"),
        ("env-password", 'PASSWORD="river stone"', "river stone"),
        ("env-prefixed", "DATABASE_PASSWORD=local-pass", "local-pass"),
        ("env-prefixed-key", "SERVICE_API_KEY=local-key", "local-key"),
        ("env-export", "export SERVICE_CLIENT_SECRET='small secret'", "small secret"),
        ("env-comment", "PASSWORD=local-pass # keep this comment", "local-pass"),
        ("http", "x-api-key: short-token\r\nAccept: text/plain", "short-token"),
        ("curl", "curl -H 'X-Api-Key: short-token' https://example.org/", "short-token"),
        ("dict", "{'password': 'river stone'}", "river stone"),
        ("logfmt", 'level=debug password="river stone" user=guest', "river stone"),
        ("log-scalar", "client_secret: short-secret, status=error", "short-secret"),
        ("punctuation", 'password="say \\"hi\\" \\ and goodbye"', 'say \\"hi\\" \\ and goodbye'),
        ("json-escaped", r'{"password":"r\u0069ver\nstone"}', r"r\u0069ver\nstone"),
        ("nested-key", '{"credentials":{"password":"small secret"}}', "small secret"),
        ("card-fragment", "api_key=prefix.4111111111111111", "prefix.4111111111111111"),
        ("empty", 'password=""', None),
        ("null", '{"password":null}', None),
        ("boolean", "password=false", None),
        ("missing", "password: \nordinary line", None),
        ("unterminated", 'password="river stone\nnext line', None),
        ("prose", "A password reset can resolve the problem.", None),
        ("generic", "token=parser-token secret=state-key pwd=current-directory", None),
        ("schema", '{"password":{"type":"string","format":"password"}}', None),
        ("suffix-control", "password_format=plain password_hash=abcdef", None),
        ("prefix-control", "notpassword=river passwordless=stone", None),
        ("expression", "password=get_password()", None),
        ("env-reference", "PASSWORD=${DATABASE_PASSWORD}", None),
        ("key-only", '{"required":["password","api_key"]}', None),
        ("array", '{"password":["river stone"]}', None),
        ("python-annotation", "def encrypt(password: str) -> None:", None),
        ("typescript-type", "interface Credentials { password: string; }", None),
        ("go-declaration", 'password := "local-pass"', None),
        ("go-loop", "for user, password := range accounts {", None),
        ("comparison", 'password == "local-pass"', None),
        ("url-path", "https://example.org/access_token=path-label", None),
    ):
        add(name, source, value)
    config = configparser.ConfigParser()
    config["credentials"] = {"password": "local-pass", "client_secret": "another-secret"}
    buffer = io.StringIO()
    config.write(buffer)
    source = buffer.getvalue()
    rows.append(
        {
            "id": "configparser",
            "source": source,
            "value": ["local-pass", "another-secret"],
            "expected": source.replace("local-pass", "⟨SECRET_1⟩").replace(
                "another-secret", "⟨SECRET_2⟩"
            ),
            "producer": "stdlib ConfigParser.write",
        }
    )
    for row in rows:
        for key in ("source", "expected"):
            if not row[key].endswith("\n"):
                row[key] += "\n"
    return rows


if __name__ == "__main__":
    (HERE / "cases.json").write_text(
        json.dumps({"provenance": __doc__, "cases": cases()}, ensure_ascii=False, indent=2) + "\n"
    )
