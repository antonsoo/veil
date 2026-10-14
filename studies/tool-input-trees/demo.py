"""Print actual SDK transport observations from synthetic tool inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))  # Wire fixtures, not product source.
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import anthropic
    from pydantic import BaseModel

    import veil
    from tests.sdk_wire import MODEL, Wire, anthropic_message
    from veil import Masker
    from veil.integrations.anthropic import AnthropicVeil
    from veil.vault import VaultError

    product = Path(veil.__file__).resolve()
    assert args.src or "site-packages" in product.parts

    class Contact(BaseModel):
        email: str

    def run(label: str, value: Any) -> None:
        wire = Wire(anthropic, lambda body: anthropic_message([{"type": "text", "text": "ok"}]))
        masker = Masker()
        with anthropic.Anthropic(api_key="unused", http_client=wire.client(), max_retries=0) as sdk:
            wrapped = AnthropicVeil(sdk, masker=masker)
            try:
                wrapped.create(
                    model=MODEL,
                    max_tokens=32,
                    messages=[
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_1",
                                    "name": "lookup",
                                    "input": value,
                                }
                            ],
                        }
                    ],
                )
            except VaultError as exc:
                print(f"{label}: {exc}")
                print(f"  HTTP calls: {len(wire.requests)}; vault entries: {len(masker.vault)}")
                assert not wire.requests and not len(masker.vault)
            else:
                sent = wire.requests[0]["messages"][0]["content"][0]["input"]
                print(f"{label}: {json.dumps(sent, ensure_ascii=False)}")
                assert "alice@example.org" not in wire.sent()

    print("Synthetic contacts; actual SDK serialization over mocked HTTP.")
    run("Tuple", {"contacts": ("alice@example.org",)})
    run("Sensitive key", {"alice@example.org": "active"})
    run("Custom object", {"contact": Contact(email="alice@example.org")})
    run(
        "Explicit plain JSON",
        {"contact": Contact(email="alice@example.org").model_dump(mode="json")},
    )


if __name__ == "__main__":
    main()
