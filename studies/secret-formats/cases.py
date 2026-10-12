"""Deterministic synthetic token shapes, never issued or authenticated credentials."""

from __future__ import annotations

import random
import string


def cases() -> list[dict[str, str | int]]:
    rng = random.Random(63021)
    rows = []
    for prefix in ("sk-proj-", "sk-svcacct-"):
        for length in (20, 32, 48, 64, 96, 128, 156, 162, 256, 4096):
            for kind, alphabet in (
                ("repeated", "a"),
                ("alphanumeric", string.ascii_letters + string.digits),
                ("url-safe", string.ascii_letters + string.digits + "_-"),
            ):
                body = "".join(rng.choices(alphabet, k=length))
                rows.append(
                    {
                        "id": f"{prefix[3:-1]}-{kind}-{length}",
                        "prefix": prefix,
                        "bodyLength": length,
                        "token": prefix + body,
                    }
                )
        for label, body in (
            ("ends-dash", "a" * 155 + "-"),
            ("ends-underscore", "a" * 155 + "_"),
            ("nested-github", "a" * 30 + "-ghp_" + "b" * 36),
            ("nested-anthropic", "a" * 30 + "-sk-ant-" + "b" * 30),
        ):
            rows.append(
                {
                    "id": f"{prefix[3:-1]}-{label}",
                    "prefix": prefix,
                    "bodyLength": len(body),
                    "token": prefix + body,
                }
            )
    return rows
