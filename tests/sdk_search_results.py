"""Controlled retrieval replies through the real SDK's HTTP serialization.

Only the HTTP endpoint is replaced. Request traversal, response models and SSE
handling belong to the installed Anthropic SDK and Veil package.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from typing import Any

import anthropic

from tests.sdk_wire import MODEL, Wire, anthropic_message, anthropic_stream
from veil import Masker
from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil

CONTACTS = ["alice@example.org", "bob@example.net", "carol@example.com", "dan@example.org"]
MODES = ["create", "raw", "helper"]
SHAPES = ["list", "tuple", "generator"]
HAS_CITATION_SNAPSHOTS = hasattr(anthropic.types, "CitationsSearchResultLocation")
EXPECTED_TEXT = "Customer bob@example.net: Contact carol@example.com. Backup dan@example.org."


def search_result() -> dict[str, Any]:
    return {
        "type": "search_result",
        "source": "account:alice@example.org",
        "title": "Customer bob@example.net",
        "content": [
            {"type": "text", "text": "Account recovery instructions."},
            {"type": "text", "text": "Contact carol@example.com."},
            {"type": "text", "text": "Backup dan@example.org."},
        ],
        "citations": {"enabled": True},
        "cache_control": {"type": "ephemeral"},
    }


def sent_results(body: dict[str, Any], nested: bool) -> list[dict[str, Any]]:
    content = body["messages"][-1]["content"]
    return content[0]["content"] if nested else content


def capture(
    nested: bool,
    shape: str,
    mode: str,
    asynchronous: bool,
    *,
    edit: Callable[[dict[str, Any]], None] | None = None,
    prefix: str | None = None,
    replay_history: bool = False,
) -> dict[str, Any]:
    result = search_result()
    if edit is not None:
        edit(result)
    parts = result["content"]
    parts_before = copy.deepcopy(parts)
    metadata_before = {k: copy.deepcopy(v) for k, v in result.items() if k != "content"}
    visits: list[int] = []

    def one_shot():
        for i, part in enumerate(parts):
            visits.append(i)
            yield part

    if shape == "tuple":
        result["content"] = tuple(parts)
    elif shape == "generator":
        result["content"] = one_shot()
    # A preceding result makes accidental flattening/reordering observable in
    # the reply's search_result_index=1 citation.
    control = {
        "type": "search_result",
        "source": "kb://public/help",
        "title": "Public help",
        "content": [{"type": "text", "text": "General guidance."}],
        "citations": {"enabled": True},
    }
    results = [control, result]
    messages = (
        [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": results}],
            },
        ]
        if nested
        else [{"role": "user", "content": results}]
    )
    if prefix is not None:
        messages.insert(0, {"role": "user", "content": prefix})
    citations: list[dict[str, Any]] = []
    provider_blocks: list[list[dict[str, Any]]] = []

    def reply(body: dict[str, Any]) -> Any:
        sent = sent_results({"messages": body["messages"][: len(messages)]}, nested)[1]
        quote = "".join(part["text"] for part in sent["content"][1:3])
        citation = {
            "type": "search_result_location",
            "source": sent["source"],
            "title": sent["title"],
            "cited_text": quote,
            "search_result_index": 1,
            "start_block_index": 1,
            "end_block_index": 3,
        }
        citations.append(citation)
        text = sent["title"] + ": " + " ".join(part["text"] for part in sent["content"][1:3])
        provider_blocks.append([{"type": "text", "text": text, "citations": [citation]}])
        if not body.get("stream"):
            return anthropic_message(provider_blocks[-1])
        # Single-character chunks split every surrogate at every boundary.
        events = anthropic_stream([("text", list(text))])
        stop = next(i for i, event in enumerate(events) if event["type"] == "content_block_stop")
        events.insert(
            stop,
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "citations_delta", "citation": citation},
            },
        )
        return events

    wire = Wire(anthropic, reply)
    masker = Masker()
    options = {"model": MODEL, "max_tokens": 128, "messages": messages}
    events: list[Any] = []
    answer: Any = None
    text = ""
    failure = None

    async def run_async() -> None:
        nonlocal answer, text
        async with anthropic.AsyncAnthropic(
            api_key="synthetic-local-only", http_client=wire.async_client(), max_retries=0
        ) as sdk:
            wrapped = AsyncAnthropicVeil(sdk, masker=masker)
            if mode == "create":
                answer = await wrapped.create(**options)
                text = answer.content[0].text
            elif mode == "raw":
                async with await wrapped.create(**options, stream=True) as stream:
                    events.extend([event async for event in stream])
            else:
                async with wrapped.stream(**options) as stream:
                    events.extend([event async for event in stream])
                    answer = await stream.get_final_message()
                    text = answer.content[0].text
            if replay_history and answer is not None:
                await wrapped.create(
                    **(
                        options
                        | {
                            "messages": [
                                *messages,
                                {"role": "assistant", "content": answer.content},
                            ]
                        }
                    )
                )

    try:
        if asynchronous:
            asyncio.run(run_async())
        else:
            with anthropic.Anthropic(
                api_key="synthetic-local-only", http_client=wire.client(), max_retries=0
            ) as sdk:
                wrapped = AnthropicVeil(sdk, masker=masker)
                if mode == "create":
                    answer = wrapped.create(**options)
                    text = answer.content[0].text
                elif mode == "raw":
                    with wrapped.create(**options, stream=True) as stream:
                        events.extend(stream)
                else:
                    with wrapped.stream(**options) as stream:
                        events.extend(stream)
                        answer = stream.get_final_message()
                        text = answer.content[0].text
                if replay_history and answer is not None:
                    wrapped.create(
                        **(
                            options
                            | {
                                "messages": [
                                    *messages,
                                    {"role": "assistant", "content": answer.content},
                                ]
                            }
                        )
                    )
    except Exception as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)}

    if events:
        deltas = [
            event.delta.text
            for event in events
            if event.type == "content_block_delta" and event.delta.type == "text_delta"
        ]
        streamed = "".join(deltas)
        if mode == "raw":
            text = streamed
        elif streamed != text:
            raise AssertionError("stream deltas differ from the SDK's final message")
    returned_citations = []
    if answer is not None:
        returned_citations.extend(getattr(answer.content[0], "citations", None) or [])
    returned_citations.extend(
        event.delta.citation
        for event in events
        if event.type == "content_block_delta" and event.delta.type == "citations_delta"
    )
    return {
        "inside_tool_result": nested,
        "shape": shape,
        "mode": mode,
        "async": asynchronous,
        "failure": failure,
        "requests": wire.requests,
        "raw_contacts_sent": [contact for contact in CONTACTS if contact in wire.sent()],
        "restored_text": text,
        "vault_entries": len(masker.vault),
        "input_unchanged": parts == parts_before
        and all(result[k] == value for k, value in metadata_before.items()),
        "iterator_visited_once": shape != "generator" or visits == list(range(len(parts))),
        "citations_unchanged": bool(returned_citations)
        and all(
            all(
                (citation.get(key) if isinstance(citation, dict) else getattr(citation, key))
                == value
                for key, value in citations[0].items()
            )
            for citation in returned_citations
        ),
        "citation_snapshot_supported": HAS_CITATION_SNAPSHOTS,
        "citation_snapshot_retained": (
            bool(getattr(answer.content[0], "citations", None))
            if answer is not None and HAS_CITATION_SNAPSHOTS
            else None
        ),
        "citation": citations[0] if citations else None,
        "assistant_replays_exactly": (
            wire.requests[1]["messages"][-1]["content"] == provider_blocks[0]
            if len(wire.requests) == 2
            else None
        ),
        "attribution_restores": bool(wire.requests)
        and all(
            masker.restore(sent_results(wire.requests[0], nested)[1][key]) == metadata_before[key]
            for key in ("source", "title")
        ),
        "package_module": __import__("veil").__file__,
        "request_json": json.dumps(wire.requests, ensure_ascii=False),
    }
