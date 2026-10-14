"""Tool input must be visited before SDK serialization can expose hidden text."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

import pytest

from tests.sdk_wire import MODEL, Wire, anthropic_message, anthropic_stream

anthropic = pytest.importorskip("anthropic")
from pydantic import BaseModel  # noqa: E402

from veil import Masker  # noqa: E402
from veil.integrations.anthropic import AnthropicVeil, AsyncAnthropicVeil  # noqa: E402
from veil.vault import VaultError  # noqa: E402

PII = "alice@example.org"
OTHER = "bob@example.net"
METHODS = ["create", "raw-stream", "helper-stream"]


class Contact(BaseModel):
    email: str


def messages(value: Any) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": f"Review contact {PII}."},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": value}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Done."}],
        },
    ]


def invoke(value: Any, asynchronous: bool, method: str, masker: Masker) -> Wire:
    def reply(body: dict[str, Any]) -> Any:
        return (
            anthropic_stream([("text", ["ok"])])
            if body.get("stream")
            else anthropic_message([{"type": "text", "text": "ok"}])
        )

    wire = Wire(anthropic, reply)
    history = messages(value)
    original = deepcopy(history)

    async def run_async() -> None:
        async with anthropic.AsyncAnthropic(
            api_key="unused", http_client=wire.async_client(), max_retries=0
        ) as sdk:
            wrapped = AsyncAnthropicVeil(sdk, masker=masker)
            args = {"model": MODEL, "max_tokens": 32, "messages": history}
            if method == "create":
                await wrapped.create(**args)
            elif method == "raw-stream":
                async for _ in await wrapped.create(**args, stream=True):
                    pass
            else:
                async with wrapped.stream(**args) as stream:
                    async for _ in stream:
                        pass

    try:
        if asynchronous:
            asyncio.run(run_async())
        else:
            with anthropic.Anthropic(
                api_key="unused", http_client=wire.client(), max_retries=0
            ) as sdk:
                wrapped = AnthropicVeil(sdk, masker=masker)
                args = {"model": MODEL, "max_tokens": 32, "messages": history}
                if method == "create":
                    wrapped.create(**args)
                elif method == "raw-stream":
                    list(wrapped.create(**args, stream=True))
                else:
                    with wrapped.stream(**args) as stream:
                        list(stream)
    finally:
        assert history == original
        # Expose actual transport capture even when preparation raises.
        invoke.last_wire = wire
    return wire


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("method", METHODS)
def test_tuples_become_masked_json_arrays_without_changing_primitives(
    asynchronous: bool, method: str
) -> None:
    huge = 2**100
    value = {"contacts": (PII, {"nested": (OTHER, huge, True, None, 1.125)})}
    wire = invoke(value, asynchronous, method, Masker())
    assert len(wire.requests) == 1
    assert PII not in wire.sent() and OTHER not in wire.sent()
    sent = wire.requests[0]["messages"][1]["content"][0]["input"]
    assert sent == {"contacts": ["⟨EMAIL_1⟩", {"nested": ["⟨EMAIL_2⟩", huge, True, None, 1.125]}]}


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("sensitive-key", "sensitive JSON key"),
        ("numeric-key", "string keys"),
        ("model", "plain JSON"),
        ("collision", "surrogate conflicts"),
    ],
)
def test_unsafe_shapes_and_tuple_collisions_reject_before_transport_and_roll_back(
    asynchronous: bool, method: str, kind: str, error: str
) -> None:
    if kind == "sensitive-key":
        value = {"normal": OTHER, "records": {PII: "active"}}
    elif kind == "numeric-key":
        value = {"normal": OTHER, "records": {4111111111111111: "active"}}
    elif kind == "model":
        value = {"normal": OTHER, "contact": Contact(email=PII)}
    else:
        value = {"normal": OTHER, "literal": ("⟨EMAIL_1⟩",)}
    masker = Masker()
    with pytest.raises(VaultError, match=error) as raised:
        invoke(value, asynchronous, method, masker)
    assert PII not in str(raised.value) and OTHER not in str(raised.value)
    assert invoke.last_wire.requests == []
    assert len(masker.vault) == 0


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_invalid_json_numbers_reject_during_preparation(number: float) -> None:
    masker = Masker()
    with pytest.raises(VaultError, match="must be finite"):
        invoke({"value": number}, False, "create", masker)
    assert invoke.last_wire.requests == []
    assert len(masker.vault) == 0


def test_explicit_model_serialization_enters_the_supported_masked_tree() -> None:
    wire = invoke(
        {"contact": Contact(email=PII).model_dump(mode="json")}, False, "create", Masker()
    )
    assert PII not in wire.sent()
    assert wire.requests[0]["messages"][1]["content"][0]["input"] == {
        "contact": {"email": "⟨EMAIL_1⟩"}
    }


def test_provider_owned_input_replays_exactly_but_an_edited_key_rejects() -> None:
    block = {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "lookup",
        "input": {"records": {PII: "active"}, "contact": "⟨email_1⟩"},
    }
    wire = Wire(anthropic, lambda body: anthropic_message([block], stop_reason="tool_use"))
    masker = Masker()
    prompt = [{"role": "user", "content": f"Review contact {PII}."}]
    with anthropic.Anthropic(api_key="unused", http_client=wire.client(), max_retries=0) as sdk:
        wrapped = AnthropicVeil(sdk, masker=masker)
        restored = wrapped.create(model=MODEL, max_tokens=32, messages=prompt).content[0]
        assert restored.input["contact"] == PII
        wrapped.create(
            model=MODEL,
            max_tokens=32,
            messages=[*prompt, {"role": "assistant", "content": [restored]}],
        )
        assert wire.requests[1]["messages"][1]["content"][0] == block
        entries = len(masker.vault)
        edited = restored.model_copy(update={"input": {"records": {OTHER: "active"}}})
        with pytest.raises(VaultError, match="sensitive JSON key"):
            wrapped.create(
                model=MODEL,
                max_tokens=32,
                messages=[*prompt, {"role": "assistant", "content": [edited]}],
            )
        assert len(wire.requests) == 2
        assert len(masker.vault) == entries
