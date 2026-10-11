"""A history match must identify its source occurrence without hiding edits."""

from copy import deepcopy

import pytest

from tests.sdk_wire import MODEL, Wire, anthropic_message, chat_completion
from veil.integrations._common import ReplayCache
from veil.integrations.anthropic import AnthropicVeil
from veil.integrations.openai import OpenAIVeil
from veil.vault import VaultError

anthropic = pytest.importorskip("anthropic")
openai = pytest.importorskip("openai")

PROMPT = [{"role": "user", "content": "Email alice@example.org."}]
ORIGINALS = ["Mailing ⟨EMAIL_1⟩.", "Mailing ⟨email_1⟩."]


@pytest.mark.parametrize("api", ["anthropic", "chat"])
@pytest.mark.parametrize("storage", ["objects", "serialized"])
def test_equal_restored_turns_keep_their_originals_or_refuse_ambiguous_copies(api, storage):
    sdk = anthropic if api == "anthropic" else openai

    def reply(body):
        text = ORIGINALS[min(len(wire.requests) - 1, 1)]
        return (
            anthropic_message([{"type": "text", "text": text}])
            if api == "anthropic"
            else chat_completion(text)
        )

    wire = Wire(sdk, reply)
    cls = sdk.Anthropic if api == "anthropic" else sdk.OpenAI
    with cls(api_key="test", http_client=wire.client(), max_retries=0) as client:
        wrapped = AnthropicVeil(client) if api == "anthropic" else OpenAIVeil(client)
        replies = [wrapped.create(model=MODEL, max_tokens=64, messages=PROMPT) for _ in range(2)]
        if api == "anthropic":
            turns = [{"role": "assistant", "content": item.content} for item in replies]
            if storage == "serialized":
                turns = [
                    {
                        "role": "assistant",
                        "content": [
                            b.model_dump(mode="json", exclude_none=True) for b in t["content"]
                        ],
                    }
                    for t in turns
                ]
        else:
            turns = [item.choices[0].message for item in replies]
            if storage == "serialized":
                turns = [t.model_dump(mode="json", exclude_none=True) for t in turns]
        # A new sensitive value before the ambiguous turn must also be rolled
        # back if request preparation fails, and no HTTP request may be sent.
        history = [
            *PROMPT,
            {"role": "user", "content": "Call bob@example.net."},
            turns[0],
            {"role": "user", "content": "Again"},
            turns[1],
        ]
        before = wrapped.masker.vault.to_dict()
        if storage == "serialized":
            with pytest.raises(VaultError, match="Ambiguous assistant history"):
                wrapped.create(model=MODEL, max_tokens=64, messages=history)
            assert len(wire.requests) == 2
            assert wrapped.masker.vault.to_dict() == before
        else:
            wrapped.create(model=MODEL, max_tokens=64, messages=history)
            sent = wire.requests[2]["messages"]
            texts = [
                sent[i]["content"][0]["text"] if api == "anthropic" else sent[i]["content"]
                for i in (2, 4)
            ]
            assert texts == ORIGINALS


def test_plain_strings_do_not_gain_occurrence_identity_from_python_interning():
    cache = ReplayCache()
    text = "same restored text"
    cache.remember(text, "first")
    cache.remember(text, "second")
    with pytest.raises(VaultError, match="Ambiguous assistant history"):
        cache.original_for(text)


def test_saved_original_and_prepared_request_are_independent_snapshots():
    cache = ReplayCache()
    restored = {"content": "alice@example.org"}
    original = {"content": "⟨EMAIL_1⟩"}
    cache.remember(restored, original)
    original["content"] = "mutated SDK response"
    prepared = cache.original_for(restored)
    assert prepared == {"content": "⟨EMAIL_1⟩"}
    prepared["content"] = "mutated outbound copy"
    assert cache.original_for(restored) == {"content": "⟨EMAIL_1⟩"}


def test_an_edited_object_is_not_replaced_by_a_different_known_turn():
    cache = ReplayCache()
    first, second = {"text": "first"}, {"text": "second"}
    cache.remember(first, {"text": "original first"})
    cache.remember(second, {"text": "original second"})
    first["text"] = "second"
    assert cache.original_for(first) is None
    assert cache.original_for(deepcopy(second)) == {"text": "original second"}


def test_identity_index_is_bounded_as_well_as_content_index():
    cache = ReplayCache(max_entries=2)
    objects = [{"text": "same"} for _ in range(3)]
    for i, obj in enumerate(objects):
        cache.remember(obj, {"text": str(i)})
    assert len(cache._objects) == 2
    assert len(cache) == 1
    with pytest.raises(VaultError, match="Ambiguous assistant history"):
        cache.original_for(objects[0])
    assert cache.original_for(objects[1]) == {"text": "1"}
    assert cache.original_for(objects[2]) == {"text": "2"}


def test_remembering_the_same_original_again_does_not_clear_ambiguity():
    cache = ReplayCache()
    for original in ["first", "second", "first"]:
        cache.remember("same", original)
    with pytest.raises(VaultError, match="Ambiguous assistant history"):
        cache.original_for("same")


@pytest.mark.parametrize("edit", ["remove", "add"])
def test_anthropic_tool_input_null_edits_reach_the_wire(edit):
    tool_input = {"to": "⟨EMAIL_1⟩", **({"limit": None} if edit == "remove" else {})}
    reply = anthropic_message(
        [{"type": "tool_use", "id": "toolu_1", "name": "send", "input": tool_input}]
    )
    wire = Wire(anthropic, lambda body: reply)
    with anthropic.Anthropic(api_key="test", http_client=wire.client(), max_retries=0) as client:
        wrapper = AnthropicVeil(client)
        first = wrapper.create(model=MODEL, max_tokens=64, messages=PROMPT)
        if edit == "remove":
            del first.content[0].input["limit"]
        else:
            first.content[0].input["limit"] = None
        wrapper.create(
            model=MODEL,
            max_tokens=64,
            messages=[*PROMPT, {"role": "assistant", "content": first.content}],
        )
    expected = {"to": "⟨EMAIL_1⟩", **({"limit": None} if edit == "add" else {})}
    assert wire.requests[1]["messages"][1]["content"][0]["input"] == expected
