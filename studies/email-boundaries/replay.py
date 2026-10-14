"""Capture mailbox masking, CLI vaults and actual SDK transports without network.

Run with the desired installed veil version, from any working directory:
    python replay.py --output results/after.json --require-fixed
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

from veil import Masker, Restorer
from veil.detectors import email as email_module

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from tests.sdk_wire import (  # noqa: E402
    MODEL,
    Wire,
    anthropic_message,
    anthropic_stream,
    chat_chunk,
    chat_completion,
    choice_delta,
    response_object,
    responses_stream,
)


def sdk_capture(source: str, api: str, asynchronous: bool, streaming: bool) -> dict[str, Any]:
    import anthropic
    import openai

    from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil
    from veil.integrations.openai import AsyncOpenAIVeil, OpenAIVeil

    sdk = anthropic if api == "anthropic" else openai

    def echo(body: dict[str, Any]) -> Any:
        text = body["input"] if api == "responses" else body["messages"][0]["content"]
        if streaming:
            if api == "responses":
                return responses_stream(list(text), [])
            if api == "anthropic":
                return anthropic_stream([("text", list(text))])
            return [
                *[chat_chunk(choice_delta(content=c)) for c in text],
                chat_chunk(choice_delta(finish="stop")),
                "[DONE]",
            ]
        if api == "responses":
            return response_object("completed", text)
        if api == "anthropic":
            return anthropic_message([{"type": "text", "text": text}])
        return chat_completion(text)

    wire = Wire(sdk, echo)
    kwargs: dict[str, Any] = {"model": MODEL}
    if streaming:
        kwargs["stream"] = True
    if api == "responses":
        kwargs["input"] = source
    else:
        kwargs["messages"] = [{"role": "user", "content": source}]
        if api == "anthropic":
            kwargs["max_tokens"] = 64

    def restored(reply: Any) -> str:
        if api == "responses":
            return str(reply.output[0].content[0].text)
        if api == "anthropic":
            return str(reply.content[0].text)
        return str(reply.choices[0].message.content)

    def pieces(events: list[Any]) -> str:
        if api == "responses":
            return "".join(
                event.delta for event in events if event.type == "response.output_text.delta"
            )
        if api == "anthropic":
            return "".join(
                event.delta.text
                for event in events
                if event.type == "content_block_delta" and event.delta.type == "text_delta"
            )
        return "".join(choice.delta.content or "" for event in events for choice in event.choices)

    async def run_async() -> str:
        client_type = sdk.AsyncAnthropic if api == "anthropic" else sdk.AsyncOpenAI
        wrapper = AsyncAnthropicVeil if api == "anthropic" else AsyncOpenAIVeil
        async with client_type(
            api_key="test", http_client=wire.async_client(), max_retries=0
        ) as client:
            wrapped = wrapper(client)
            call = wrapped.create_response if api == "responses" else wrapped.create
            reply = await call(**kwargs)
            if streaming:
                return pieces([event async for event in reply])
            return restored(reply)

    if asynchronous:
        reply_text = asyncio.run(run_async())
    else:
        client_type = sdk.Anthropic if api == "anthropic" else sdk.OpenAI
        wrapper = AnthropicVeil if api == "anthropic" else OpenAIVeil
        with client_type(api_key="test", http_client=wire.client(), max_retries=0) as client:
            wrapped = wrapper(client)
            call = wrapped.create_response if api == "responses" else wrapped.create
            reply = call(**kwargs)
            reply_text = pieces(list(reply)) if streaming else restored(reply)
    assert reply_text == source
    assert len(wire.requests) == 1
    request = wire.requests[0]
    outgoing = request["input"] if api == "responses" else request["messages"][0]["content"]
    return {
        "api": api,
        "async": asynchronous,
        "stream": streaming,
        "request": request,
        "outgoing": outgoing,
        "restoresExactly": True,
    }


def cli(*args: str, source: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "veil.cli", *args],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stderr == "", result.stderr
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-fixed", action="store_true")
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory(prefix="veil-email-boundaries-") as directory:
        for case in json.loads((HERE / "cases.json").read_text())["cases"]:
            address = case["address"]
            source = f"Contact <{address}> today.\n"
            expected = "Contact <⟨EMAIL_1⟩> today.\n" if case["mask"] else source
            masker = Masker()
            masked = masker.mask(source)
            assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
            for size in (1, 2, 7, 31):
                restorer = Restorer(masker.vault)
                reply = "".join(
                    restorer.feed(masked[i : i + size]) for i in range(0, len(masked), size)
                )
                assert reply + restorer.flush() == source
            vault_path = Path(directory) / (case["id"] + ".json")
            cli_masked = cli("mask", "--vault", str(vault_path), source=source)
            assert cli_masked == masked
            assert cli("restore", "--exact", "--vault", str(vault_path), source=masked) == source
            captures = [
                sdk_capture(source, api, asynchronous, streaming)
                for api in ("chat", "responses", "anthropic")
                for asynchronous in (False, True)
                for streaming in (False, True)
            ]
            row = {
                **case,
                "source": source,
                "masked": masked,
                "expected": expected,
                "completeMask": masked == expected,
                "vault": json.loads(vault_path.read_text()),
                "sdk": captures,
            }
            assert all(c["outgoing"] == masked for c in captures)
            if args.require_fixed:
                assert row["completeMask"], row
            rows.append(row)
    result = {
        "python": sys.version,
        "emailSourceSha256": hashlib.sha256(Path(email_module.__file__).read_bytes()).hexdigest(),
        "versions": {p: version(p) for p in ("veil-pii", "openai", "anthropic")},
        "casesSha256": hashlib.sha256((HERE / "cases.json").read_bytes()).hexdigest(),
        "cases": rows,
        "completeCases": sum(r["completeMask"] for r in rows),
        "sdkRequests": sum(len(r["sdk"]) for r in rows),
        "transport": "Actual installed SDKs over httpx MockTransport; synthetic echo responses, no provider request.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{result['completeCases']}/{len(rows)} complete cases; {result['sdkRequests']} SDK requests"
    )


if __name__ == "__main__":
    main()
