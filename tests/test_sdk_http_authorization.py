"""Actual SDK serialization must retain a header key's masking context."""

import asyncio
import runpy
from pathlib import Path

import pytest

from tests.sdk_wire import MODEL
from tests.test_sdk_mask_collisions import client_for
from veil import VaultError

capture = runpy.run_path(
    str(Path(__file__).parents[1] / "studies/http-authorization/sdk_tools.py")
)["sdk_tool_capture"]


@pytest.mark.parametrize("api", ["chat", "responses", "anthropic"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_auth_headers_in_tool_history_are_wholly_masked_before_transport(
    api: str, asynchronous: bool, streaming: bool
) -> None:
    result = capture(api, asynchronous, streaming)
    assert result["correct"]
    assert result["unrelatedSyntaxPreserved"]


@pytest.mark.parametrize("api", ["chat", "responses", "anthropic"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("source", ["Authorization: Basic dXNlcjpwYXNz", 'password="river stone"'])
def test_header_credential_collision_rolls_back_before_sdk_transport(
    api: str, asynchronous: bool, source: str
) -> None:
    wrapped, wire = client_for(api, asynchronous)
    kwargs = {"model": MODEL}
    if api == "responses":
        kwargs.update(input=source, instructions="Literal \u27e8SECRET_1\u27e9")
    else:
        kwargs["messages"] = [
            {"role": "user", "content": source},
            {"role": "user", "content": "Literal \u27e8SECRET_1\u27e9"},
        ]
        if api == "anthropic":
            kwargs["max_tokens"] = 64
    call = wrapped.create_response if api == "responses" else wrapped.create
    before = wrapped.masker.vault.to_json()
    if asynchronous:

        async def run() -> None:
            try:
                with pytest.raises(VaultError, match="conflicts"):
                    await call(**kwargs)
            finally:
                await wrapped.client.close()

        asyncio.run(run())
    else:
        try:
            with pytest.raises(VaultError, match="conflicts"):
                call(**kwargs)
        finally:
            wrapped.client.close()
    assert wire.requests == []
    assert wrapped.masker.vault.to_json() == before
