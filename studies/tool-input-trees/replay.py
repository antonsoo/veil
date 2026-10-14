"""Observe actual SDK requests for synthetic JSON-tree and serialization controls."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PII = "alice@example.org"
OTHER = "bob@example.net"
CARD = 4111111111111111  # Synthetic detector control; no issued-card claim.
METHODS = ("create", "raw-stream", "helper-stream")
KINDS = (
    "tuple",
    "sensitive-key",
    "numeric-key",
    "opaque-model",
    "tuple-collision",
    "plain-json",
    "serialized-model",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, help="omit only for an installed wheel")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observe-only", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))  # Independent wire fixtures, never product source.
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import anthropic
    from pydantic import BaseModel

    import veil
    from tests.sdk_wire import MODEL, Wire, anthropic_message, anthropic_stream
    from veil import Masker
    from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil

    product = Path(veil.__file__).resolve()
    if args.src:
        assert product.is_relative_to(args.src.resolve())
    else:
        assert "site-packages" in product.parts, "Use --src for editable/source installations"

    class Contact(BaseModel):
        email: str

    def value(kind: str) -> dict[Any, Any]:
        if kind == "tuple":
            return {"contacts": (PII, {"nested": (OTHER, 2**100, True, None, 1.125)})}
        if kind == "sensitive-key":
            return {"normal": OTHER, "records": {PII: "active"}}
        if kind == "numeric-key":
            return {"normal": OTHER, "records": {CARD: "active"}}
        if kind == "opaque-model":
            return {"normal": OTHER, "contact": Contact(email=PII)}
        if kind == "tuple-collision":
            return {"normal": OTHER, "literal": ("⟨EMAIL_1⟩",)}
        if kind == "serialized-model":
            return {"contact": Contact(email=PII).model_dump(mode="json")}
        return {"contact": PII, "nested": [OTHER, 2**100, False, None, 1.125]}

    def run(kind: str, asynchronous: bool, method: str) -> dict[str, Any]:
        history = [
            {"role": "user", "content": f"Review contact {PII}."},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": value(kind)}
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Done."}],
            },
        ]
        before = deepcopy(history)
        masker = Masker()
        failure = None

        def reply(body: dict[str, Any]) -> Any:
            return (
                anthropic_stream([("text", ["ok"])])
                if body.get("stream")
                else anthropic_message([{"type": "text", "text": "ok"}])
            )

        wire = Wire(anthropic, reply)

        async def asynchronous_run() -> None:
            nonlocal failure
            async with anthropic.AsyncAnthropic(
                api_key="unused", http_client=wire.async_client(), max_retries=0
            ) as sdk:
                wrapped = AsyncAnthropicVeil(sdk, masker=masker)
                call_args = {"model": MODEL, "max_tokens": 32, "messages": history}
                try:
                    if method == "create":
                        await wrapped.create(**call_args)
                    elif method == "raw-stream":
                        async for _ in await wrapped.create(**call_args, stream=True):
                            pass
                    else:
                        async with wrapped.stream(**call_args) as stream:
                            async for _ in stream:
                                pass
                except Exception as exc:
                    failure = {"type": type(exc).__name__, "message": str(exc)}

        if asynchronous:
            asyncio.run(asynchronous_run())
        else:
            with anthropic.Anthropic(
                api_key="unused", http_client=wire.client(), max_retries=0
            ) as sdk:
                wrapped = AnthropicVeil(sdk, masker=masker)
                call_args = {"model": MODEL, "max_tokens": 32, "messages": history}
                try:
                    if method == "create":
                        wrapped.create(**call_args)
                    elif method == "raw-stream":
                        list(wrapped.create(**call_args, stream=True))
                    else:
                        with wrapped.stream(**call_args) as stream:
                            list(stream)
                except Exception as exc:
                    failure = {"type": type(exc).__name__, "message": str(exc)}
        unchanged = history == before
        recognized_raw = [text for text in (PII, OTHER, str(CARD)) if text in wire.sent()]
        reject = kind in ("sensitive-key", "numeric-key", "opaque-model", "tuple-collision")
        if reject:
            agrees = (
                failure is not None
                and failure["type"] == "VaultError"
                and not wire.requests
                and len(masker.vault) == 0
                and unchanged
            )
        else:
            agrees = (
                failure is None and len(wire.requests) == 1 and not recognized_raw and unchanged
            )
            if agrees and kind == "tuple":
                actual = wire.requests[0]["messages"][1]["content"][0]["input"]
                agrees = actual == {
                    "contacts": ["⟨EMAIL_1⟩", {"nested": ["⟨EMAIL_2⟩", 2**100, True, None, 1.125]}]
                }
        return {
            "kind": kind,
            "method": method,
            "async": asynchronous,
            "expected": "reject" if reject else "mask",
            "failure": failure,
            "requests": wire.requests,
            "transportCalls": len(wire.requests),
            "recognizedRawValuesSent": recognized_raw,
            "callerInputUnchanged": unchanged,
            "vaultEntriesAfter": len(masker.vault),
            "agrees": agrees,
        }

    results = [
        run(kind, asynchronous, method)
        for kind in KINDS
        for asynchronous in (False, True)
        for method in METHODS
    ]
    for asynchronous in (False, True):
        block = {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "lookup",
            "input": {"records": {PII: "active"}, "contact": "⟨email_1⟩"},
        }
        wire = Wire(
            anthropic,
            lambda body, result=block: anthropic_message([result], stop_reason="tool_use"),
        )
        prompt = [{"role": "user", "content": f"Review contact {PII}."}]

        async def replay_async(wire: Any, prompt: list[dict[str, Any]]) -> None:
            async with anthropic.AsyncAnthropic(
                api_key="unused", http_client=wire.async_client(), max_retries=0
            ) as sdk:
                wrapped = AsyncAnthropicVeil(sdk)
                restored = (
                    await wrapped.create(model=MODEL, max_tokens=32, messages=prompt)
                ).content[0]
                await wrapped.create(
                    model=MODEL,
                    max_tokens=32,
                    messages=[*prompt, {"role": "assistant", "content": [restored]}],
                )

        if asynchronous:
            asyncio.run(replay_async(wire, prompt))
        else:
            with anthropic.Anthropic(
                api_key="unused", http_client=wire.client(), max_retries=0
            ) as sdk:
                wrapped = AnthropicVeil(sdk)
                restored = wrapped.create(model=MODEL, max_tokens=32, messages=prompt).content[0]
                wrapped.create(
                    model=MODEL,
                    max_tokens=32,
                    messages=[*prompt, {"role": "assistant", "content": [restored]}],
                )
        agrees = wire.requests[1]["messages"][1]["content"][0] == block
        results.append(
            {
                "kind": "provider-replay",
                "async": asynchronous,
                "method": "create",
                "expected": "exact provider-owned replay; provider's pre-existing key is not fresh caller data",
                "requests": wire.requests,
                "agrees": agrees,
            }
        )
    mismatches = sum(not entry["agrees"] for entry in results)
    record = {
        "python": sys.version.split()[0],
        "sdk": {
            "anthropic": importlib.metadata.version("anthropic"),
            "pydantic": importlib.metadata.version("pydantic"),
        },
        "runtimeSourceSha256": hashlib.sha256(
            (product.parent / "integrations/_common.py").read_bytes()
        ).hexdigest(),
        "population": "Synthetic contacts, card-shaped detector control and controlled SDK replies over mocked HTTP transport. No live provider acceptance, inference or data-protection guarantee.",
        "count": len(results),
        "disagreements": mismatches,
        "freshCallerRequestsWithRecognizedRawValues": sum(
            bool(entry.get("recognizedRawValuesSent")) for entry in results
        ),
        "cases": results,
    }
    args.out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(
        f"{len(results)} real SDK/mock workflows; {mismatches} disagreements; {record['freshCallerRequestsWithRecognizedRawValues']} fresh raw-value request cases."
    )
    if mismatches and not args.observe_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
