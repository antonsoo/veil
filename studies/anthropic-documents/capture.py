"""Capture synthetic document requests through the actual Anthropic SDK, offline.

Use --source CHECKOUT to select source, or omit it to check an installed wheel.
The shared test helper supplies only HTTP response envelopes and mock transport.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import platform
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path)
parser.add_argument("--check", action="store_true")
parser.add_argument("--label", default="installed")
parser.add_argument("--summary", action="store_true")
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if args.source:
    sys.path.insert(0, str(args.source.resolve() / "src"))

import anthropic  # noqa: E402

from tests.sdk_wire import MODEL, Wire, anthropic_message, anthropic_stream  # noqa: E402
from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil  # noqa: E402

CONTACTS = ["alice@example.com", "bob@example.org", "carol@example.net"]
BODY = "Contact alice@example.com about this order."
IMAGE = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA=="}}


def document(shape):
    source = {
        "plain": {"type": "text", "media_type": "text/plain", "data": BODY},
        "content-string": {"type": "content", "content": BODY},
        "content-blocks": {
            "type": "content",
            "content": [{"type": "text", "text": BODY}, IMAGE],
        },
    }[shape]
    return {
        "type": "document",
        "source": copy.deepcopy(source),
        "title": "Record for bob@example.org",
        "context": "Owner carol@example.net",
        "citations": {"enabled": True},
        "cache_control": {"type": "ephemeral"},
    }


def messages_for(shape, nested):
    doc = document(shape)
    if nested:
        return [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_fixture",
                        "name": "read_record",
                        "input": {},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_fixture",
                        "content": [doc],
                    }
                ],
            },
        ]
    return [{"role": "user", "content": [doc, {"type": "text", "text": "Who is the contact?"}]}]


def sent_document(body, nested):
    block = body["messages"][-1]["content"][0]
    return block["content"][0] if nested else block


def document_text(doc):
    source = doc["source"]
    if source["type"] == "text":
        return source["data"]
    content = source["content"]
    return content if isinstance(content, str) else content[0]["text"]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


async def capture(shape, nested, mode, asynchronous):
    original = messages_for(shape, nested)
    untouched = copy.deepcopy(original)

    def reply(body):
        text = document_text(sent_document(body, nested))
        if body.get("stream"):
            # Fragment inside a possible placeholder, not just between words.
            return anthropic_stream([("text", [text[:12], text[12:17], text[17:]])])
        return anthropic_message([{"type": "text", "text": text}])

    wire = Wire(anthropic, reply)
    options = {"model": MODEL, "max_tokens": 128, "messages": original}
    if asynchronous:
        async with anthropic.AsyncAnthropic(
            api_key="synthetic-local-only", http_client=wire.async_client(), max_retries=0
        ) as sdk:
            wrapped = AsyncAnthropicVeil(sdk)
            if mode == "create":
                restored = (await wrapped.create(**options)).content[0].text
            elif mode == "raw":
                async with await wrapped.create(**options, stream=True) as stream:
                    restored = "".join(
                        [e.delta.text async for e in stream if e.type == "content_block_delta"]
                    )
            else:
                async with wrapped.stream(**options) as stream:
                    restored = "".join([piece async for piece in stream.text_stream])
                    assert (await stream.get_final_message()).content[0].text == restored
    else:
        with anthropic.Anthropic(
            api_key="synthetic-local-only", http_client=wire.client(), max_retries=0
        ) as sdk:
            wrapped = AnthropicVeil(sdk)
            if mode == "create":
                restored = wrapped.create(**options).content[0].text
            elif mode == "raw":
                with wrapped.create(**options, stream=True) as stream:
                    restored = "".join(
                        e.delta.text for e in stream if e.type == "content_block_delta"
                    )
            else:
                with wrapped.stream(**options) as stream:
                    restored = "".join(stream.text_stream)
                    assert stream.get_final_message().content[0].text == restored
    assert len(wire.requests) == 1
    request = wire.requests[0]
    sent = sent_document(request, nested)
    leaks = [contact for contact in CONTACTS if contact in json.dumps(request)]
    checks = {
        "detected_contacts_absent": not leaks,
        "caller_input_unchanged": original == untouched,
        "answer_restored": restored == BODY,
        "source_shape_unchanged": sent["source"]["type"] == document(shape)["source"]["type"],
        "citation_control_unchanged": sent["citations"] == {"enabled": True},
        "cache_control_unchanged": sent["cache_control"] == {"type": "ephemeral"},
        "image_unchanged": shape != "content-blocks" or sent["source"]["content"][1] == IMAGE,
    }
    if args.check:
        assert all(checks.values()), (shape, nested, mode, asynchronous, checks)
    row = {
        "shape": shape,
        "inside_tool_result": nested,
        "mode": mode,
        "async": asynchronous,
        "request_sha256": digest(request),
        "unmasked_contacts": leaks,
        "checks": checks,
    }
    if mode == "create" and not asynchronous:
        row["request"] = request
        row["restored_answer"] = restored
    return row


async def main():
    rows = []
    for shape in ["plain", "content-string", "content-blocks"]:
        for nested in [False, True]:
            for mode in ["create", "raw", "helper"]:
                for asynchronous in [False, True]:
                    rows.append(await capture(shape, nested, mode, asynchronous))
    if args.summary:
        print(f"Anthropic {anthropic.__version__}: 36 SDK requests through local mock HTTP")
        print("Mode coverage: sync/async create, raw streams, helper streams")
        print("Placement: direct documents and documents inside tool results\n")
        print("Document source        Requests with detected contacts still visible")
        for shape in ["plain", "content-string", "content-blocks"]:
            selected = [row for row in rows if row["shape"] == shape]
            leaks = sum(bool(row["unmasked_contacts"]) for row in selected)
            print(f"{shape:22s} {leaks} / {len(selected)}")
        print(f"\nRestored answers: {sum(row['checks']['answer_restored'] for row in rows)} / 36")
        print("\nExample document serialized by the SDK:")
        print(
            json.dumps(
                rows[0]["request"]["messages"][0]["content"][0], indent=2, ensure_ascii=False
            )
        )
        return
    print(
        json.dumps(
            {
                "label": args.label,
                "python": platform.python_version(),
                "anthropic": anthropic.__version__,
                "scope": "Synthetic documents; actual SDK with local mock transport; no model or network calls.",
                "cases": rows,
                "request_count": len(rows),
                "requests_with_unmasked_contacts": sum(
                    bool(row["unmasked_contacts"]) for row in rows
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


asyncio.run(main())
