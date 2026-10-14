"""Actual SDK transport captures; all replies and contacts are controlled fixtures."""

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
PII = "alice@example.com"
FIELDS = ("refusal", "refusal-part", "legacy", "custom")
OUTPUT_FIELDS = ("refusal", "legacy", "custom")


def text_for(kind: str, address: str) -> str:
    if kind == "legacy":
        return '{\n "to": "' + address + '", "n": 9007199254740993, "x": 1, "x": 2\n}'
    return f"Cannot contact {address}."


def history(kind: str, text: str) -> dict[str, Any]:
    item: dict[str, Any] = {"role": "assistant", "content": None}
    if kind == "refusal":
        item["refusal"] = text
    elif kind == "refusal-part":
        item["content"] = [{"type": "refusal", "refusal": text}]
    elif kind == "legacy":
        item["function_call"] = {"name": "contact", "arguments": text}
    else:
        item["tool_calls"] = [
            {
                "id": "call_1",
                "type": "custom",
                "custom": {"name": "contact", "input": text},
            }
        ]
    return item


def field(item: dict[str, Any], kind: str) -> str:
    if kind == "refusal":
        return item["refusal"]
    if kind == "refusal-part":
        return item["content"][0]["refusal"]
    if kind == "legacy":
        return item["function_call"]["arguments"]
    return item["tool_calls"][0]["custom"]["input"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, help="omit only when running an installed wheel")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--observe-only", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))  # Independent wire fixtures, not product source.
    if args.src:
        sys.path.insert(0, str(args.src.resolve()))
    import openai

    import veil
    from tests.sdk_wire import MODEL, Wire, chat_chunk, chat_completion, choice_delta
    from veil.integrations.openai import AsyncOpenAIVeil, OpenAIVeil

    product = Path(veil.__file__).resolve()
    if args.src:
        assert product.is_relative_to(args.src.resolve())
    else:
        assert "site-packages" in product.parts, "Use --src for an editable/source installation"

    def run(kind: str, operation: str, asynchronous: bool, mode: str) -> dict:
        source = [history(kind, text_for(kind, PII))]
        if operation == "collision":
            source = [
                {"role": "user", "content": f"Contact {PII}"},
                history(kind, text_for(kind, "⟨EMAIL_1⟩")),
            ]
        elif operation == "restore-and-replay":
            source = [{"role": "user", "content": f"Contact {PII}"}]
        before = deepcopy(source)
        provider_text = text_for(kind, "⟨email_1⟩")
        provider = chat_completion(None)
        provider["choices"][0]["message"] = history(kind, provider_text)

        def response(body: dict) -> Any:
            if body.get("stream"):
                return [
                    chat_chunk(choice_delta(content="ok")),
                    chat_chunk(choice_delta(finish="stop")),
                    "[DONE]",
                ]
            return provider if operation == "restore-and-replay" else chat_completion("ok")

        wire = Wire(openai, response)
        returned = None
        failure = None
        vault_size = None

        async def async_call(wrapped: Any) -> None:
            nonlocal returned
            if mode == "stream":
                stream = await wrapped.stream(model=MODEL, messages=source)
                async with stream:
                    async for _ in stream:
                        pass
            elif mode == "create-stream":
                stream = await wrapped.create(model=MODEL, messages=source, stream=True)
                async with stream:
                    async for _ in stream:
                        pass
            else:
                result = await wrapped.create(model=MODEL, messages=source)
                if operation == "restore-and-replay":
                    restored = result.choices[0].message
                    returned = restored.model_dump(exclude_none=True)
                    await wrapped.create(model=MODEL, messages=[*source, restored])

        async def asynchronous_run() -> None:
            nonlocal failure, vault_size
            async with openai.AsyncOpenAI(
                api_key="test",
                http_client=wire.async_client(),
                max_retries=0,
            ) as sdk:
                wrapped = AsyncOpenAIVeil(sdk)
                try:
                    await async_call(wrapped)
                except (
                    Exception
                ) as exc:  # Record failures instead of discarding the before evidence.
                    failure = {"type": type(exc).__name__, "message": str(exc)}
                vault_size = len(wrapped.masker.vault)

        if asynchronous:
            asyncio.run(asynchronous_run())
        else:
            with openai.OpenAI(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
                wrapped = OpenAIVeil(sdk)
                try:
                    if mode in ("stream", "create-stream"):
                        stream = (
                            wrapped.stream(model=MODEL, messages=source)
                            if mode == "stream"
                            else wrapped.create(model=MODEL, messages=source, stream=True)
                        )
                        with stream:
                            list(stream)
                    else:
                        result = wrapped.create(model=MODEL, messages=source)
                        if operation == "restore-and-replay":
                            restored = result.choices[0].message
                            returned = restored.model_dump(exclude_none=True)
                            wrapped.create(model=MODEL, messages=[*source, restored])
                except Exception as exc:
                    failure = {"type": type(exc).__name__, "message": str(exc)}
                vault_size = len(wrapped.masker.vault)

        leaked = PII in wire.sent()
        unchanged = source == before
        if operation == "collision":
            agrees = (
                failure is not None
                and failure["type"] == "VaultError"
                and not wire.requests
                and vault_size == 0
                and unchanged
            )
        elif operation == "restore-and-replay":
            agrees = (
                failure is None
                and returned is not None
                and field(returned, kind) == text_for(kind, PII)
                and len(wire.requests) == 2
                and field(wire.requests[-1]["messages"][-1], kind) == provider_text
                and not leaked
                and unchanged
            )
        else:
            expected = history(kind, text_for(kind, "⟨EMAIL_1⟩"))
            agrees = (
                failure is None
                and len(wire.requests) == 1
                and wire.requests[0]["messages"] == [expected]
                and not leaked
                and unchanged
            )
        return {
            "field": kind,
            "operation": operation,
            "client": "async" if asynchronous else "sync",
            "entrypoint": mode,
            "source": before,
            "provider_reply": provider if operation == "restore-and-replay" else None,
            "returned": returned,
            "requests": wire.requests,
            "failure": failure,
            "raw_contact_sent": leaked,
            "source_unchanged": unchanged,
            "vault_size": vault_size,
            "agrees": agrees,
        }

    cases = [
        run(kind, operation, asynchronous, mode)
        for kind in FIELDS
        for operation in ("mask", "collision")
        for asynchronous in (False, True)
        for mode in ("create", "create-stream", "stream")
    ] + [
        run(kind, "restore-and-replay", asynchronous, "create")
        for kind in OUTPUT_FIELDS
        for asynchronous in (False, True)
    ]
    code = product.parent / "integrations/openai.py"
    result = {
        "scope": "54 real SDK / mocked transport workflows; synthetic emails, no live API calls",
        "python": sys.version.split()[0],
        "openai": importlib.metadata.version("openai"),
        "source_override": args.src is not None,
        "product_origin": "source" if args.src else "installed site-packages",
        "integration_sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
        "transport_fixture_sha256": hashlib.sha256(
            (ROOT / "tests/sdk_wire.py").read_bytes()
        ).hexdigest(),
        "count": len(cases),
        "disagreements": sum(not case["agrees"] for case in cases),
        "raw_contact_sent_cases": sum(case["raw_contact_sent"] for case in cases),
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(
        f"{result['count']} SDK workflows; {result['disagreements']} disagreements; "
        f"{result['raw_contact_sent_cases']} request bodies with raw contacts"
    )
    if result["disagreements"] and not args.observe_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
