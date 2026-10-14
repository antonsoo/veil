"""Print actual local SDK transport observations; no network API calls."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import openai

    from tests.sdk_wire import MODEL, Wire, chat_completion
    from veil.integrations.openai import OpenAIVeil

    reply = chat_completion(None)
    reply["choices"][0]["message"]["refusal"] = "Cannot contact ⟨email_1⟩."
    wire = Wire(openai, lambda body: reply)
    with openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
        wrapped = OpenAIVeil(sdk)
        result = wrapped.create(
            model=MODEL,
            messages=[
                {
                    "role": "assistant",
                    "content": None,
                    "refusal": "Cannot contact alice@example.com.",
                }
            ],
        )
        restored = result.choices[0].message
        print("SDK request refusal:", wire.requests[0]["messages"][0]["refusal"])
        print("Application receives:", restored.refusal)
        wrapped.create(model=MODEL, messages=[restored])
        print("Unchanged history replay:", wire.requests[1]["messages"][0]["refusal"])
        assert "alice@example.com" not in wire.sent()


if __name__ == "__main__":
    main()
