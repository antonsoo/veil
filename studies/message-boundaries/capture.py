"""Replay synthetic message boundaries through real SDK clients, without network calls."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Any

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--label", default="installed")
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

import anthropic  # noqa: E402
import openai  # noqa: E402

from tests.sdk_wire import (  # noqa: E402
    MODEL,
    Wire,
    anthropic_message,
    anthropic_stream,
    chat_completion,
)
from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil  # noqa: E402
from veil.integrations.openai import OpenAIVeil  # noqa: E402
from veil.vault import VaultError  # noqa: E402

PROMPT = [{"role": "user", "content": "Email alice@example.com and bob@example.org."}]
BLOCKS = {
    "within-one-block": [("text", ["First ⟨EM", "AIL_1⟩"])],
    "across-text-blocks": [("text", ["First ⟨EM"]), ("text", ["AIL_1⟩ second ⟨EMAIL_2⟩"])],
    "across-tool-block": [
        ("text", ["First ⟨EM"]),
        ("tool_use", ['{"to":"⟨EMAIL_2⟩"}']),
        ("text", ["AIL_1⟩ second ⟨EMAIL_2⟩"]),
    ],
    "empty-text-block": [("text", ["⟨EM"]), ("text", []), ("text", ["AIL_1⟩"])],
}
results: list[dict[str, Any]] = []


def record(case: str, checks: dict[str, bool], **evidence: Any) -> None:
    results.append({"case": case, **evidence, "checks": checks, "agrees": all(checks.values())})


def expected_text(blocks: list[tuple[str, list[str]]]) -> str:
    # Independent oracle: replacement happens in each complete text block, then joining.
    return "".join(
        "".join(chunks)
        .replace("⟨EMAIL_1⟩", "alice@example.com")
        .replace("⟨EMAIL_2⟩", "bob@example.org")
        for kind, chunks in blocks
        if kind == "text"
    )


async def streams() -> None:
    for case, blocks in BLOCKS.items():
        expected = expected_text(blocks)
        for mode in ("sync", "async"):
            wire = Wire(anthropic, lambda body, blocks=blocks: anthropic_stream(blocks))
            if mode == "sync":
                with anthropic.Anthropic(
                    api_key="synthetic-local-test", http_client=wire.client(), max_retries=0
                ) as client:
                    wrapped = AnthropicVeil(client)
                    with wrapped.stream(model=MODEL, max_tokens=64, messages=PROMPT) as stream:
                        chunks = list(stream.text_stream)
                        final_text = stream.get_final_text()
                        final = stream.get_final_message()
            else:
                async with anthropic.AsyncAnthropic(
                    api_key="synthetic-local-test", http_client=wire.async_client(), max_retries=0
                ) as client:
                    wrapped = AsyncAnthropicVeil(client)
                    async with wrapped.stream(
                        model=MODEL, max_tokens=64, messages=PROMPT
                    ) as stream:
                        chunks = [chunk async for chunk in stream.text_stream]
                        final_text = await stream.get_final_text()
                        final = await stream.get_final_message()
            record(
                f"{mode}/{case}",
                {
                    "stream_respects_blocks": "".join(chunks) == expected,
                    "final_text_respects_blocks": final_text == expected,
                    "final_blocks_agree": "".join(b.text for b in final.content if b.type == "text")
                    == expected,
                },
                input_blocks=blocks,
                emitted_chunks=chunks,
                final_text=final_text,
                expected_text=expected,
            )


def history() -> None:
    originals = ["Mailing ⟨EMAIL_1⟩.", "Mailing ⟨email_1⟩."]
    for api in ("anthropic", "chat"):
        for storage in ("objects", "serialized"):
            sdk = anthropic if api == "anthropic" else openai

            replies = iter(
                [
                    anthropic_message([{"type": "text", "text": text}])
                    if api == "anthropic"
                    else chat_completion(text)
                    for text in [*originals, originals[-1]]
                ]
            )

            wire = Wire(sdk, lambda body, replies=replies: next(replies))
            client_type = sdk.Anthropic if api == "anthropic" else sdk.OpenAI
            with client_type(
                api_key="synthetic-local-test", http_client=wire.client(), max_retries=0
            ) as client:
                wrapper = AnthropicVeil(client) if api == "anthropic" else OpenAIVeil(client)
                first = wrapper.create(model=MODEL, max_tokens=64, messages=PROMPT)
                second = wrapper.create(model=MODEL, max_tokens=64, messages=PROMPT)
                if api == "anthropic":
                    turns = [
                        {"role": "assistant", "content": item.content} for item in (first, second)
                    ]
                    if storage == "serialized":
                        turns = [
                            {
                                "role": "assistant",
                                "content": [
                                    b.model_dump(mode="json", exclude_none=True)
                                    for b in t["content"]
                                ],
                            }
                            for t in turns
                        ]
                else:
                    turns = [item.choices[0].message for item in (first, second)]
                    if storage == "serialized":
                        turns = [item.model_dump(mode="json", exclude_none=True) for item in turns]
                failure = None
                replayed = None
                try:
                    wrapper.create(
                        model=MODEL,
                        max_tokens=64,
                        messages=[
                            *PROMPT,
                            turns[0],
                            {"role": "user", "content": "Again"},
                            turns[1],
                        ],
                    )
                    messages = wire.requests[-1]["messages"]
                    replayed = [
                        messages[i]["content"][0]["text"]
                        if api == "anthropic"
                        else messages[i]["content"]
                        for i in (1, 3)
                    ]
                except VaultError as error:
                    failure = str(error)
            record(
                f"{api}/history/{storage}",
                {
                    "preserves_identity_or_refuses_ambiguity": (
                        replayed == originals
                        if storage == "objects"
                        else failure is not None and len(wire.requests) == 2
                    ),
                },
                original_texts=originals,
                replayed_texts=replayed,
                error=failure,
                requests_sent=len(wire.requests),
            )


def edited_and_user_history() -> None:
    for edit in ("remove-null", "add-null"):
        original = {"to": "⟨EMAIL_1⟩", **({"limit": None} if edit == "remove-null" else {})}
        response = anthropic_message(
            [{"type": "tool_use", "id": "toolu_1", "name": "send", "input": original}]
        )
        wire = Wire(anthropic, lambda body, response=response: response)
        with anthropic.Anthropic(
            api_key="synthetic-local-test", http_client=wire.client(), max_retries=0
        ) as client:
            wrapper = AnthropicVeil(client)
            first = wrapper.create(model=MODEL, max_tokens=64, messages=PROMPT)
            if edit == "remove-null":
                del first.content[0].input["limit"]
            else:
                first.content[0].input["limit"] = None
            wrapper.create(
                model=MODEL,
                max_tokens=64,
                messages=[*PROMPT, {"role": "assistant", "content": first.content}],
            )
        sent = wire.requests[1]["messages"][1]["content"][0]["input"]
        expected = {"to": "⟨EMAIL_1⟩", **({"limit": None} if edit == "add-null" else {})}
        record(
            f"anthropic/history/{edit}",
            {"edit_preserved": sent == expected},
            original_input=original,
            expected_input=expected,
            sent_input=sent,
        )

    for form in ("string", "blocks"):
        response = anthropic_message([{"type": "text", "text": "Contact help@example.org."}])
        wire = Wire(anthropic, lambda body, response=response: response)
        with anthropic.Anthropic(
            api_key="synthetic-local-test", http_client=wire.client(), max_retries=0
        ) as client:
            wrapper = AnthropicVeil(client)
            first = wrapper.create(
                model=MODEL, max_tokens=64, messages=[{"role": "user", "content": "Hello"}]
            )
            content = first.content[0].text if form == "string" else first.content
            wrapper.create(
                model=MODEL, max_tokens=64, messages=[{"role": "user", "content": content}]
            )
        sent = wire.requests[1]["messages"][0]["content"]
        record(
            f"anthropic/user/{form}",
            {"user_text_masked": "help@example.org" not in str(sent) and "⟨EMAIL_1⟩" in str(sent)},
            original_text=response["content"][0]["text"],
            sent_content=sent,
        )


asyncio.run(streams())
history()
edited_and_user_history()
receipt = {
    "label": args.label,
    "python": platform.python_version(),
    "anthropic_sdk": importlib.metadata.version("anthropic"),
    "openai_sdk": importlib.metadata.version("openai"),
    "scope": "Synthetic local HTTP captures through real SDKs. No provider calls or real personal data.",
    "cases": len(results),
    "disagreements": sum(not row["agrees"] for row in results),
    "results": results,
}
print(json.dumps(receipt, ensure_ascii=False, indent=2))
if args.check and receipt["disagreements"]:
    raise SystemExit(1)
