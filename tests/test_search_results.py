"""Retrieval content must be masked before the SDK serializes it."""

from __future__ import annotations

import asyncio

import pytest

anthropic = pytest.importorskip("anthropic")

from tests.sdk_search_results import (  # noqa: E402
    EXPECTED_TEXT,
    HAS_CITATION_SNAPSHOTS,
    MODES,
    SHAPES,
    capture,
    sent_results,
)
from tests.sdk_wire import MODEL, Wire, anthropic_message  # noqa: E402
from veil import Masker  # noqa: E402
from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil  # noqa: E402


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("asynchronous", [False, True])
def test_retrieved_content_and_metadata_are_masked_at_transport(
    nested: bool, shape: str, mode: str, asynchronous: bool
) -> None:
    result = capture(nested, shape, mode, asynchronous)
    assert result["failure"] is None
    assert len(result["requests"]) == 1
    assert result["raw_contacts_sent"] == []
    assert result["vault_entries"] == 4
    assert result["restored_text"] == EXPECTED_TEXT
    assert result["input_unchanged"]
    assert result["iterator_visited_once"]
    assert result["citations_unchanged"]
    assert result["attribution_restores"]
    if HAS_CITATION_SNAPSHOTS and mode != "raw":
        assert result["citation_snapshot_retained"]
    sent = sent_results(result["requests"][0], nested)
    assert len(sent) == 2
    assert sent[0]["source"] == "kb://public/help"
    assert sent[0]["content"] == [{"type": "text", "text": "General guidance."}]
    target = sent[1]
    assert target["source"] == "account:⟨EMAIL_1⟩"
    assert target["title"] == "Customer ⟨EMAIL_2⟩"
    assert [part["text"] for part in target["content"]] == [
        "Account recovery instructions.",
        "Contact ⟨EMAIL_3⟩.",
        "Backup ⟨EMAIL_4⟩.",
    ]
    assert target["cache_control"] == {"type": "ephemeral"}
    assert target["citations"] == {"enabled": True}


@pytest.mark.parametrize("field", ["source", "title", "content"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("mode", MODES)
def test_retrieval_literals_participate_in_request_collision_checks(
    field: str, asynchronous: bool, mode: str
) -> None:
    def edit(result: dict) -> None:
        if field == "content":
            result["content"][-1]["text"] = "Literal ⟨EMAIL_1⟩."
        else:
            result[field] += " Literal ⟨EMAIL_1⟩."

    # An earlier message allocates EMAIL_1 before retrieval is visited.
    result = capture(
        True, "generator", mode, asynchronous, edit=edit, prefix="Seed erin@example.invalid."
    )
    assert result["failure"]["type"] == "VaultError"
    assert result["requests"] == []
    assert result["vault_entries"] == 0
    assert all(
        contact not in result["failure"]["message"]
        for contact in (
            "alice@example.org",
            "bob@example.net",
            "carol@example.com",
            "dan@example.org",
        )
    )


def test_signed_retrieval_locator_is_masked_as_one_url() -> None:
    signed = "https://kb.example.invalid/file?X-Amz-Signature=synthetic&X-Amz-Credential=synthetic"
    result = capture(False, "list", "create", False, edit=lambda block: block.update(source=signed))
    assert result["failure"] is None
    assert signed not in result["request_json"]
    assert sent_results(result["requests"][0], False)[1]["source"] == "⟨URL_CREDENTIAL_1⟩"
    assert result["citation"]["source"] == "⟨URL_CREDENTIAL_1⟩"
    assert result["attribution_restores"]


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("mode", ["create", "helper"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_restored_answers_replay_exact_provider_text_and_citations(
    nested: bool, mode: str, asynchronous: bool
) -> None:
    if mode == "helper" and not HAS_CITATION_SNAPSHOTS:
        pytest.skip("this SDK predates search-result citation snapshots")
    result = capture(nested, "list", mode, asynchronous, replay_history=True)
    assert result["failure"] is None
    assert result["assistant_replays_exactly"]
    assert result["raw_contacts_sent"] == []
    assert result["restored_text"] == EXPECTED_TEXT


@pytest.mark.parametrize("asynchronous", [False, True])
def test_failed_retrieval_iterator_preserves_the_existing_vault(asynchronous: bool) -> None:
    masker = Masker()
    masker.mask("Existing eve@example.org.")
    before = masker.vault.to_dict()
    visits = []

    def parts():
        visits.append("yield")
        yield {"type": "text", "text": "New alice@example.org."}
        visits.append("fail")
        raise RuntimeError("synthetic retrieval failure")

    wire = Wire(anthropic, lambda body: anthropic_message([]))
    args = {
        "model": MODEL,
        "max_tokens": 32,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "search_result",
                        "source": "kb://public",
                        "title": "Public",
                        "content": parts(),
                    }
                ],
            }
        ],
    }

    async def run_async() -> None:
        async with anthropic.AsyncAnthropic(
            api_key="unused", http_client=wire.async_client(), max_retries=0
        ) as sdk:
            with pytest.raises(RuntimeError, match="synthetic retrieval failure"):
                await AsyncAnthropicVeil(sdk, masker=masker).create(**args)

    if asynchronous:
        asyncio.run(run_async())
    else:
        with (
            anthropic.Anthropic(api_key="unused", http_client=wire.client(), max_retries=0) as sdk,
            pytest.raises(RuntimeError, match="synthetic retrieval failure"),
        ):
            AnthropicVeil(sdk, masker=masker).create(**args)
    assert visits == ["yield", "fail"]
    assert not wire.requests
    assert masker.vault.to_dict() == before
