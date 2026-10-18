from __future__ import annotations

import json
from pathlib import Path

import pytest

from veil import Masker, Restorer, VaultError
from veil.integrations._common import mask_value
from veil.integrations._json_arguments import mask_arguments, restore_arguments

DIRECTORY = Path(__file__).parents[1] / "studies/har-headers/fixtures"
ORACLE = json.loads((DIRECTORY / "oracle.json").read_text())


def har_text(headers: str = "[]", cookies: str = "[]") -> str:
    return (
        '{"log":{"version":"1.2","entries":[{"request":{"headers":'
        + headers
        + ',"cookies":'
        + cookies
        + "}}]}}"
    )


@pytest.mark.parametrize("record", ORACLE["rows"], ids=lambda row: row["engine"])
def test_native_browser_cookie_surfaces_and_exact_source(record: dict[str, object]) -> None:
    source = (DIRECTORY / str(record["file"])).read_text()
    for transform in [lambda text, masker: masker.mask(text), mask_arguments]:
        masker = Masker()
        masked = transform(source, masker)
        assert str(record["session"]) not in masked
        assert json.loads(masked)["log"]["version"] == "1.2"
        # This source has ordinary cookie bytes, not nested JSON escapes;
        # both raw and decoded-value paths restore the exact native file.
        assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
        restorer = Restorer(masker.vault)
        assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source
        assert restore_arguments(masked, masker) == source


def test_cookie_context_preserves_json_spelling_and_only_replaces_values() -> None:
    source = r'{"count":90071992547409931234567890,"count":1.2300e+400,"har": {"lo\u0067":{"version":"1.2","entries":[{"request":{"headers":[{"na\u006de":"Co\u006fkie","value":"sid=sh\u006frt"}],"cookies":[{"name":"sid","value":"sh\u006frt","expires":-1.000}]}}]}}}'
    raw = Masker()
    masked = raw.mask(source)
    assert masked == source.replace(r"sid=sh\u006frt", "⟨SECRET_1⟩").replace(
        r"sh\u006frt", "⟨SECRET_2⟩"
    )
    assert raw.restore(masked) == source
    decoded = Masker()
    masked = mask_arguments(source, decoded)
    assert masked == source.replace(r"sid=sh\u006frt", "⟨SECRET_1⟩").replace(
        r"sh\u006frt", "⟨SECRET_2⟩"
    )
    assert json.loads(restore_arguments(masked, decoded)) == json.loads(source)
    assert ',"count":1.2300e+400,' in masked
    assert '"expires":-1.000' in masked


@pytest.mark.parametrize(
    "source",
    [
        har_text('[{"name":"Cookie","name":"X-Public","value":"sid=short"}]'),
        har_text('[{"name":"Cookie","value":"sid=short","value":"sid=other"}]'),
        har_text('"not-an-array"'),
        har_text('[{"name":"Cookie","value":17}]'),
        har_text("[]", '[{"name":"sid","value":"short","value":"other"}]'),
        '{"log":{"version":"1.2","entries":[],"entries":[{"request":{}}]}}',
        '{"log":{"version":"1.2","entries":[]},"log":{"version":"1.2","entries":[]}}',
    ],
)
def test_ambiguous_har_routing_refuses_without_vault_changes(source: str) -> None:
    for transform in [lambda text, masker: masker.mask(text), mask_arguments]:
        masker = Masker()
        before = masker.vault.to_json()
        with pytest.raises(VaultError, match="HAR"):
            transform(source, masker)
        assert masker.vault.to_json() == before


@pytest.mark.parametrize(
    "source",
    [
        '{"headers":[{"name":"Cookie","value":"sid=short"}]}',
        '{"cookies":[{"name":"chocolate","value":"crispy"}]}',
        '{"log":{"version":"other","entries":[{"request":{"cookies":[{"name":"sid","value":"short"}]}}]}}',
        '{"Cookie":["short",{"public":"other"}]}',
        '{"Cookie":{"public":"short"}}',
        '{"Cookie":17,"Set-Cookie":true}',
        '{"Cookie":null,"public":"short"}',
        'type Headers = { "set-cookie": string[]; };',
    ],
)
def test_no_cookie_context_is_inferred_outside_declared_shapes(source: str) -> None:
    assert Masker().mask(source) == source
    assert mask_arguments(source, Masker()) == source


def test_complete_json_cookie_keys_are_decoded_without_invented_source_text() -> None:
    source = r'{"Co\u006fkie":"sid=short"}'
    masker = Masker()
    assert masker.mask(source) == r'{"Co\u006fkie":"⟨SECRET_1⟩"}'
    assert masker.restore(r'{"Co\u006fkie":"⟨SECRET_1⟩"}') == source


def test_restore_does_not_require_a_model_reply_to_be_valid_har() -> None:
    masker = Masker()
    assert masker.mask("Cookie: sid=short") == "Cookie: ⟨SECRET_1⟩"
    reply = '{"log":{"version":"1.2","entries":"⟨SECRET_1⟩"}}'
    assert restore_arguments(reply, masker) == '{"log":{"version":"1.2","entries":"sid=short"}}'


def test_disabling_field_detectors_does_not_enforce_har_routing() -> None:
    source = har_text('[{"name":"Cookie","name":"X-Public","value":"short"}]')
    assert mask_arguments(source, Masker(detectors=[])) == source


@pytest.mark.parametrize("record", ORACLE["rows"], ids=lambda row: row["engine"])
def test_structured_tool_inputs_use_the_same_har_context(record: dict[str, object]) -> None:
    source = json.loads((DIRECTORY / str(record["file"])).read_text())
    original = json.dumps(source, sort_keys=True)
    masked = mask_value(source, Masker())
    assert str(record["session"]) not in json.dumps(masked)
    assert json.dumps(source, sort_keys=True) == original
    assert masked["log"]["version"] == source["log"]["version"]


def test_structured_har_keeps_unsafe_integers_and_tuple_arrays() -> None:
    source = {
        "log": {
            "version": "1.2",
            "entries": ({"request": {"cookies": ({"name": "sid", "value": "short"},)}},),
        },
        "count": 2**200,
    }
    masked = mask_value(source, Masker())
    assert masked["count"] == 2**200
    assert masked["log"]["entries"][0]["request"]["cookies"][0]["value"] == "⟨SECRET_1⟩"
    assert source["log"]["entries"][0]["request"]["cookies"][0]["value"] == "short"


def test_cycles_refuse_before_any_structured_value_is_prepared() -> None:
    source: dict[str, object] = {"contact": "alice@example.org"}
    source["cycle"] = source
    masker = Masker()
    with pytest.raises(VaultError, match="cycles"):
        mask_value(source, masker)
    assert len(masker.vault) == 0
