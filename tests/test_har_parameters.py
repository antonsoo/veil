from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from veil import Masker, Restorer, VaultError
from veil.detectors import EmailDetector
from veil.integrations._common import mask_value, restore_value
from veil.integrations._json_arguments import mask_arguments, restore_arguments

FIXTURES = Path(__file__).parents[1] / "studies/har-parameters/fixtures"
ORACLE = json.loads((FIXTURES / "oracle.json").read_text())


def har(request: dict[str, object]) -> str:
    return json.dumps({"log": {"version": "1.2", "entries": [{"request": request}]}})


@pytest.mark.parametrize("item", ORACLE["rows"], ids=lambda item: item["engine"])
def test_native_browser_and_proxy_credentials_survive_no_public_surfaces(item: dict) -> None:
    source = (FIXTURES / item["file"]).read_text()
    document = json.loads(source)
    for mode in ["raw", "arguments", "tree"]:
        masker = Masker()
        original = copy.deepcopy(document)
        if mode == "tree":
            data = mask_value(document, masker)
            assert restore_value(data, masker) == document
        else:
            masked = masker.mask(source) if mode == "raw" else mask_arguments(source, masker)
            data = json.loads(masked)
            assert (
                masker.restore(masked) if mode == "raw" else restore_arguments(masked, masker)
            ) == source
            if mode == "raw":
                restorer = Restorer(masker.vault)
                assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source
        assert document == original
        for surface in item["surfaces"]:
            value = data
            for key in surface["path"].strip("/").split("/"):
                value = value[int(key)] if isinstance(value, list) else value[key]
            assert re.fullmatch(r"⟨(?:SECRET|URL_CREDENTIAL)_\d+⟩", value)


@pytest.mark.parametrize(
    "name", ["password", "X-Api-Key", "client_secret", "refresh_token", "SERVICE_PASSWORD"]
)
def test_named_header_query_and_form_values_keep_credential_context(name: str) -> None:
    record = {"name": name, "value": 'short "private"\nvalue'}
    source = har({"headers": [record], "queryString": [record], "postData": {"params": [record]}})
    masker = Masker()
    masked = mask_arguments(source, masker)
    assert json.loads(masked)["log"]["entries"][0]["request"] == {
        "headers": [{"name": name, "value": "⟨SECRET_1⟩"}],
        "queryString": [{"name": name, "value": "⟨SECRET_1⟩"}],
        "postData": {"params": [{"name": name, "value": "⟨SECRET_1⟩"}]},
    }
    assert json.loads(restore_arguments(masked, masker)) == json.loads(source)


def test_encoded_names_and_multiline_mime_values_keep_the_whole_original_container() -> None:
    body = '--b\r\nContent-Disposition: form-data; name="password"\r\n\r\none\r\ntwo\r\n--b--\r\n'
    source = har(
        {
            "url": "https://example.invalid/?client%5fsecret=short&format=json",
            "postData": {"mimeType": 'multipart/form-data; boundary="b"', "text": body},
        }
    )
    masker = Masker()
    masked = masker.mask(source)
    request = json.loads(masked)["log"]["entries"][0]["request"]
    assert request["url"] == "⟨SECRET_1⟩" and request["postData"]["text"] == "⟨SECRET_2⟩"
    assert masker.restore(masked) == source


@pytest.mark.parametrize("kind", ["headers", "queryString", "params"])
def test_ambiguous_parameter_routing_refuses_before_changing_the_vault(kind: str) -> None:
    records = '[{"name":"password","name":"format","value":"short"}]'
    request = f'"postData":{{"params":{records}}}' if kind == "params" else f'"{kind}":{records}'
    source = '{"log":{"version":"1.2","entries":[{"request":{' + request + "}}]}}"
    for operation in [lambda value, masker: masker.mask(value), mask_arguments]:
        masker = Masker()
        before = masker.vault.to_json()
        with pytest.raises(VaultError, match="HAR"):
            operation(source, masker)
        assert masker.vault.to_json() == before


@pytest.mark.parametrize(
    "body", ["not multipart", '--b\r\nContent-Disposition: form-data; name="password"\r\n\r\nshort']
)
def test_incomplete_mime_refuses_without_partially_masking_a_har(body: str) -> None:
    source = har({"postData": {"mimeType": "multipart/form-data; boundary=b", "text": body}})
    masker = Masker()
    before = masker.vault.to_json()
    with pytest.raises(VaultError, match="HAR multipart"):
        masker.mask(source)
    assert masker.vault.to_json() == before


def test_public_parameter_names_and_non_har_records_do_not_gain_http_header_semantics() -> None:
    records = [
        {"name": name, "value": "public"} for name in ["format", "Cookie", "Authorization", "token"]
    ]
    source = har(
        {
            "queryString": records,
            "postData": {
                "params": records,
                "mimeType": "application/x-www-form-urlencoded",
                "text": "format=json&token=public",
            },
        }
    )
    assert Masker().mask(source) == source
    assert mask_arguments(source, Masker()) == source
    ordinary = json.dumps({"params": [{"name": "password", "value": "short"}]})
    assert Masker().mask(ordinary) == ordinary


def test_disabled_field_detection_keeps_its_existing_scope() -> None:
    source = har(
        {"postData": {"mimeType": "multipart/form-data; boundary=b", "text": "incomplete"}}
    )
    assert mask_arguments(source, Masker(detectors=[EmailDetector()])) == source


def test_opaque_mime_secret_owns_nested_email_url_and_card_matches() -> None:
    body = '--b\r\nContent-Disposition: form-data; name="password"\r\n\r\nalice@example.org https://bob:pass@example.org 4111111111111111\r\n--b--\r\n'
    source = har({"postData": {"mimeType": "multipart/form-data; boundary=b", "text": body}})
    for operation in [lambda value, masker: masker.mask(value), mask_arguments]:
        masker = Masker()
        masked = operation(source, masker)
        assert (
            json.loads(masked)["log"]["entries"][0]["request"]["postData"]["text"] == "⟨SECRET_1⟩"
        )


def test_duplicate_mime_names_cannot_select_a_different_field_context() -> None:
    body = '--b\r\nContent-Disposition: form-data; name="password"; name="format"\r\n\r\nshort\r\n--b--\r\n'
    source = har({"postData": {"mimeType": "multipart/form-data; boundary=b", "text": body}})
    masker = Masker()
    before = masker.vault.to_json()
    with pytest.raises(VaultError, match="HAR multipart"):
        mask_arguments(source, masker)
    assert masker.vault.to_json() == before


@pytest.mark.parametrize(
    "headers",
    [
        'Content-Disposition: form-data; name="format"\r\nContent-Disposition: form-data; name="password"',
        'Content-Type: text/plain\r\nContent-Type: application/json\r\nContent-Disposition: form-data; name="password"',
    ],
)
def test_duplicate_mime_routing_headers_refuse_instead_of_selecting_the_first(headers: str) -> None:
    body = "--b\r\n" + headers + "\r\n\r\nshort\r\n--b--\r\n"
    source = har({"postData": {"mimeType": "multipart/form-data; boundary=b", "text": body}})
    for operation in [lambda value, masker: masker.mask(value), mask_arguments]:
        masker = Masker()
        before = masker.vault.to_json()
        with pytest.raises(VaultError, match="HAR multipart"):
            operation(source, masker)
        assert masker.vault.to_json() == before
