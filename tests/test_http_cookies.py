from __future__ import annotations

import json

import pytest

from veil import Masker, Restorer
from veil.integrations._json_arguments import mask_arguments


@pytest.mark.parametrize(
    "source,secret",
    [
        ("Cookie: sid=s1; theme=dark\r\nHost: example.org\r\n", "sid=s1; theme=dark"),
        (
            "Set-Cookie: sid=s1; Expires=Wed, 09 Jun 2027 10:18:14 GMT; HttpOnly",
            "sid=s1; Expires=Wed, 09 Jun 2027 10:18:14 GMT; HttpOnly",
        ),
        ('{"Cookie": "sid=s1; theme=dark", "count": 2}', "sid=s1; theme=dark"),
        ("curl -H 'Cookie: sid=s1; theme=dark' https://example.org/", "sid=s1; theme=dark"),
        ('curl -H "Set-Cookie: sid=s1; Path=/" https://example.org/', "sid=s1; Path=/"),
        ("cOoKiE:\tsid=s1 \t\n", "sid=s1"),
        ('Cookie: sid="abc"; other=def', 'sid="abc"; other=def'),
        ("Cookie: sid=4111111111111111; password=short", "sid=4111111111111111; password=short"),
        ("password='Cookie: sid=abc'", "Cookie: sid=abc"),
        ('{"Cookie":"sid=abc\\"def; tail=secret","next":"public"}', 'sid=abc\\"def; tail=secret'),
    ],
)
def test_complete_cookie_header_value(source: str, secret: str) -> None:
    masker = Masker()
    masked = masker.mask(source)
    assert masked == source.replace(secret, "⟨SECRET_1⟩", 1)
    assert masker.restore(masked) == masker.restore(masked, tolerant=False) == source
    assert [(m.original, m.type.value) for m in masker.vault.mappings()] == [(secret, "SECRET")]
    restorer = Restorer(masker.vault)
    assert "".join(restorer.feed(c) for c in masked) + restorer.flush() == source


@pytest.mark.parametrize("name", ["Cookie", "cookie", "Set-Cookie", "sEt-CoOkIe"])
def test_decoded_cookie_field_and_tool_arguments(name: str) -> None:
    value = 'sid=short; quoted="a,b"; theme=dark'
    masker = Masker()
    assert masker.mask(value, field_name=name) == "⟨SECRET_1⟩"
    assert masker.restore("⟨SECRET_1⟩") == value
    source = json.dumps({"headers": {name: value}, "public": 17})
    masker = Masker()
    assert json.loads(mask_arguments(source, masker)) == {
        "headers": {name: "⟨SECRET_1⟩"},
        "public": 17,
    }


@pytest.mark.parametrize(
    "source",
    [
        "I like a cookie.",
        "cookie_count: 17",
        "X-Cookie: short",
        "Set-Cookies: short",
        "Cookie:\r\nNext: public",
        "Cookie: \nCookie: \n",
    ],
)
def test_cookie_label_boundaries(source: str) -> None:
    assert Masker().mask(source) == source


def test_each_set_cookie_field_stays_separate() -> None:
    source = "Set-Cookie: sid=short; HttpOnly\r\nSet-Cookie: refresh=r1; Path=/\r\n"
    masker = Masker()
    assert masker.mask(source) == "Set-Cookie: ⟨SECRET_1⟩\r\nSet-Cookie: ⟨SECRET_2⟩\r\n"
