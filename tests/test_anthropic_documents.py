"""Document privacy at the actual SDK transport boundary, with no remote calls."""

from __future__ import annotations

import copy
import json
from collections import deque
from typing import Any

import pytest

from tests.sdk_wire import MODEL, Wire, anthropic_message, anthropic_stream
from veil import Masker, VaultError
from veil.integrations.anthropic import AnthropicVeil

anthropic = pytest.importorskip("anthropic")


@pytest.mark.parametrize("container", [list, tuple, iter, deque])
def test_masks_document_text_through_each_sdk_content_iterable(container: Any) -> None:
    text = "Email alice@example.com."
    image = {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AA=="},
    }
    doc = {
        "type": "document",
        "source": {
            "type": "content",
            "content": container([{"type": "text", "text": text}, image]),
        },
        "title": "bob@example.org",
        "context": "carol@example.net",
        "citations": {"enabled": True},
        "cache_control": {"type": "ephemeral"},
    }
    content = container([{"type": "tool_result", "tool_use_id": "t1", "content": container([doc])}])
    wire = Wire(anthropic, lambda body: anthropic_message([{"type": "text", "text": "Received."}]))
    with anthropic.Anthropic(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
        wrapped = AnthropicVeil(sdk)
        wrapped.create(model=MODEL, max_tokens=64, messages=[{"role": "user", "content": content}])
    assert all(
        address not in wire.sent()
        for address in ["alice@example.com", "bob@example.org", "carol@example.net"]
    )
    sent = wire.requests[0]["messages"][0]["content"][0]["content"][0]
    assert wrapped.masker.restore(sent["source"]["content"][0]["text"]) == text
    assert sent["source"]["content"][1] == image
    assert sent["citations"] == doc["citations"]
    assert sent["cache_control"] == doc["cache_control"]


@pytest.mark.parametrize(
    "source",
    [
        {"type": "base64", "media_type": "application/pdf", "data": "AA=="},
        {"type": "url", "url": "https://example.org/document.pdf"},
        {"type": "file", "file_id": "file_fixture"},
    ],
)
def test_opaque_document_sources_are_preserved_but_metadata_is_masked(source: dict) -> None:
    doc = {
        "type": "document",
        "source": source,
        "title": "alice@example.com",
        "context": "bob@example.org",
    }
    original = copy.deepcopy(doc)
    wire = Wire(anthropic, lambda body: anthropic_message([{"type": "text", "text": "Received."}]))
    with anthropic.Anthropic(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
        AnthropicVeil(sdk).create(
            model=MODEL, max_tokens=64, messages=[{"role": "user", "content": [doc]}]
        )
    sent = wire.requests[0]["messages"][0]["content"][0]
    assert sent["source"] == source
    assert doc == original
    assert "alice@example.com" not in wire.sent() and "bob@example.org" not in wire.sent()


def test_document_literal_collision_rolls_back_before_transport() -> None:
    wire = Wire(anthropic, lambda body: anthropic_message([]))
    masker = Masker()
    before = masker.vault.to_dict()
    with anthropic.Anthropic(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
        wrapped = AnthropicVeil(sdk, masker=masker)
        with pytest.raises(VaultError):
            wrapped.create(
                model=MODEL,
                max_tokens=64,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Email alice@example.com"},
                            {
                                "type": "document",
                                "source": {
                                    "type": "text",
                                    "media_type": "text/plain",
                                    "data": "Literal example: ⟨EMAIL_1⟩",
                                },
                            },
                        ],
                    }
                ],
            )
    assert not wire.requests
    assert masker.vault.to_dict() == before


def test_citation_coordinates_and_quote_stay_in_provider_space_during_replay() -> None:
    """Restoring an answer must not silently relabel masked-source character offsets."""
    doc = {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": "alice@example.com"},
    }
    replies = []

    def reply(body: dict) -> dict:
        masked = body["messages"][0]["content"][0]["source"]["data"]
        block = {
            "type": "text",
            "text": masked,
            "citations": [
                {
                    "type": "char_location",
                    "cited_text": masked,
                    "document_index": 0,
                    "document_title": None,
                    "start_char_index": 0,
                    "end_char_index": len(masked),
                }
            ],
        }
        replies.append(block)
        return anthropic_message([block])

    wire = Wire(anthropic, reply)
    with anthropic.Anthropic(api_key="test", http_client=wire.client(), max_retries=0) as sdk:
        wrapped = AnthropicVeil(sdk)
        messages = [{"role": "user", "content": [doc]}]
        answer = wrapped.create(model=MODEL, max_tokens=64, messages=messages)
        assert answer.content[0].text == "alice@example.com"
        citation = json.loads(answer.content[0].model_dump_json())["citations"][0]
        expected_citation = replies[0]["citations"][0]
        assert {key: citation[key] for key in expected_citation} == expected_citation
        assert citation["end_char_index"] == len(citation["cited_text"])
        assert citation["cited_text"] != doc["source"]["data"]
        wrapped.create(
            model=MODEL,
            max_tokens=64,
            messages=[*messages, {"role": "assistant", "content": answer.content}],
        )
    assert wire.requests[1]["messages"][1]["content"] == [replies[0]]
    assert "alice@example.com" not in wire.sent()


def test_streamed_citation_keeps_the_masked_source_quote_and_offsets() -> None:
    citation = {}

    def reply(body: dict) -> list:
        masked = body["messages"][0]["content"][0]["source"]["data"]
        citation.update(
            {
                "type": "char_location",
                "cited_text": masked,
                "document_index": 0,
                "document_title": None,
                "start_char_index": 0,
                "end_char_index": len(masked),
            }
        )
        events = anthropic_stream([("text", [masked[:5], masked[5:]])])
        stop = next(i for i, e in enumerate(events) if e["type"] == "content_block_stop")
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
    doc = {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": "alice@example.com"},
    }
    with (
        anthropic.Anthropic(api_key="test", http_client=wire.client(), max_retries=0) as sdk,
        AnthropicVeil(sdk).stream(
            model=MODEL, max_tokens=64, messages=[{"role": "user", "content": [doc]}]
        ) as stream,
    ):
        events = list(stream)
        answer = stream.get_final_message()
    assert answer.content[0].text == "alice@example.com"
    raw = next(
        e.delta.citation
        for e in events
        if e.type == "content_block_delta" and e.delta.type == "citations_delta"
    )
    for key, value in citation.items():
        assert getattr(raw, key) == value
        assert getattr(answer.content[0].citations[0], key) == value
    assert "alice@example.com" not in wire.sent()
