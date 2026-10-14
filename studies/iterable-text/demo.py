"""Print real SDK transport observations for synthetic iterable text."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))  # Independent transport fixtures.
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import openai

    import veil
    from tests.sdk_iterable_text import capture

    origin = Path(veil.__file__).resolve()
    assert args.src or "site-packages" in origin.parts
    print(f"OpenAI SDK {openai.__version__}; synthetic contacts over mocked HTTP.")
    print(f"{'Input':<33} {'HTTP calls':>10} {'Raw contact':>13} {'Vault entries':>14}")
    for kind, shape in [
        ("chat-text", "tuple"),
        ("chat-text", "generator"),
        ("chat-refusal", "tuple"),
        ("response-content", "generator"),
        ("response-summary", "tuple"),
        ("response-input", "tuple"),
    ]:
        result = capture(kind, shape, False, "complete")
        assert result["failure"] is None and not result["recognizedRawContactSent"]
        print(
            f"{kind + ' / ' + shape:<33} {len(result['requests']):>10} "
            f"{str(result['recognizedRawContactSent']):>13} {result['vaultEntriesAfter']:>14}"
        )
    collision = capture("chat-text", "generator", False, "complete", collision=True)
    assert collision["failure"]["type"] == "VaultError" and not collision["requests"]
    assert collision["vaultEntriesAfter"] == 0
    print("Generator literal collision: VaultError; HTTP calls 0; vault entries 0.")
    print("One-shot iterators are consumed during preparation, including failures.")


if __name__ == "__main__":
    main()
