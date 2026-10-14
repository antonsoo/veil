"""Complete identities, syntax oracle controls and bounded invalid candidates."""

from __future__ import annotations

import json
from email.headerregistry import Address
from pathlib import Path

import pytest

from veil import Masker
from veil.detectors.email import EmailDetector

CASES = json.loads((Path(__file__).parents[1] / "studies/email-boundaries/cases.json").read_text())[
    "cases"
]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_whole_mailbox_or_no_mailbox(case: dict[str, object]) -> None:
    address = str(case["address"])
    source = f"Contact <{address}> today."
    entities = EmailDetector().find(source)
    assert [e.value for e in entities] == ([address] if case["mask"] else [])
    assert all(source[e.span.start : e.span.end] == e.value for e in entities)
    masker = Masker()
    masked = masker.mask(source)
    assert masked == ("Contact <⟨EMAIL_1⟩> today." if case["mask"] else source)
    assert masker.restore(masked, tolerant=False) == source


@pytest.mark.parametrize("punctuation", list("!#$%&'*+-/=?^_`{|}~"))
@pytest.mark.parametrize("local", ["{p}private", "private{p}name", "private{p}"])
def test_all_ascii_atext_preserves_complete_identity(punctuation: str, local: str) -> None:
    address = local.format(p=punctuation) + "@example.org"
    # Python's independent RFC header parser accepts the complete mailbox.
    assert Address(addr_spec=address).username == local.format(p=punctuation)
    assert [e.value for e in EmailDetector().find(f"<{address}>")] == [address]


@pytest.mark.parametrize(
    "address",
    [
        '"private name"@example.org',
        '"private@name"@example.org',
        '"private\\"name"@example.org',
        '"private\\\\name"@example.org',
        '"private@example.net"@example.org',
        '"contact private@example.net today"@example.org',
    ],
)
def test_quoted_local_against_independent_parser(address: str) -> None:
    assert Address(addr_spec=address).domain == "example.org"
    assert [e.value for e in EmailDetector().find(address)] == [address]


@pytest.mark.parametrize("wrapper", ['"', "'", "`", "", "("])
def test_prose_delimiters_and_trailing_full_stop(wrapper: str) -> None:
    close = ")" if wrapper == "(" else wrapper
    text = f"Contact {wrapper}alice@example.org{close}."
    assert [e.value for e in EmailDetector().find(text)] == ["alice@example.org"]


@pytest.mark.parametrize(
    "address",
    [
        "a" * 65 + "@example.org",
        "é" * 33 + "@example.org",
        '"' + "a" * 63 + '"@example.org',
        "a@" + "b" * 64 + ".org",
        "a@" + ".".join(["b" * 63] * 4) + ".org",
        "a@example.org+suffix",
        "a@example.org_suffix",
        "a@example..org",
        "a@-example.org",
        "a@example.org-",
        "a@example.123",
        "a@example.xn--",
        "a@example\u200b.org",
        "private\u200bname@example.org",
        "private😀name@example.org",
        "a@example.org@other.org",
        "'@example.org'",
        "`@example.org`",
        "``@app.route()``",
        "`@click.command`",
    ],
)
def test_invalid_or_unsupported_token_never_becomes_a_shorter_mailbox(address: str) -> None:
    assert EmailDetector().find(address) == []


def test_octet_limits_and_domains_with_maximum_label_length() -> None:
    for address in ["a" * 64 + "@example.org", "é" * 32 + "@example.org", "a@example." + "b" * 63]:
        assert [e.value for e in EmailDetector().find(address)] == [address]


def test_multiple_quoted_and_unquoted_addresses_keep_source_order() -> None:
    addresses = ['"private@name"@example.org', "a!b@example.net", "c@example.org"]
    assert [e.value for e in EmailDetector().find(", ".join(addresses))] == addresses


def test_existing_mailto_and_calendar_account_contact_boundaries() -> None:
    for source in [
        "mailto:@private@example.org",
        "@private@example.org",
        "[Account private@example.org@https://calendar.example.org/users/id]",
    ]:
        assert [e.value for e in EmailDetector().find(source)] == ["private@example.org"]
