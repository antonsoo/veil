"""Actual SDK serialization/restoration for contextual credentials in tool JSON."""

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
fixture = runpy.run_path(str(ROOT / "studies/credential-fields/replay.py"))
capture = runpy.run_path(str(ROOT / "studies/http-authorization/sdk_tools.py"))["sdk_tool_capture"]


@pytest.mark.parametrize("api", ["chat", "responses", "anthropic"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_labelled_credentials_keep_context_and_json_restoration(
    api: str, asynchronous: bool, streaming: bool
) -> None:
    result = capture(
        api,
        asynchronous,
        streaming,
        source=fixture["RAW"],
        expected=fixture["EXPECTED"],
        tool_reply=True,
    )
    assert result["correct"]
    assert result["unrelatedSyntaxPreserved"]
