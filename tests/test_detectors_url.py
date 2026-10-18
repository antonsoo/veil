import pytest

from veil import Masker
from veil.detectors.url import UrlCredentialDetector

d = UrlCredentialDetector()


@pytest.mark.parametrize(
    "name", ["client_secret", "refresh_token", "passwd", "x-api-key", "SERVICE_PASSWORD"]
)
@pytest.mark.parametrize("component", ["?", "#", "#/callback?"])
def test_explicit_credential_fields_protect_whole_urls_with_wordlike_values(
    name: str, component: str
) -> None:
    source = "https://example.invalid/callback" + component + name + "=wordlike"
    masker = Masker()
    assert masker.mask(source) == "⟨URL_CREDENTIAL_1⟩"
    assert masker.restore("⟨URL_CREDENTIAL_1⟩") == source


def test_new_url_field_aliases_decode_names_once_without_inventing_fields_from_values() -> None:
    source = "https://example.invalid/?client%5fsecret=wordlike"
    assert [item.value for item in d.find(source)] == [source]
    for source in [
        "https://example.invalid/?client_secret=",
        "https://example.invalid/?client%255fsecret=wordlike",
        "https://example.invalid/?format=client_secret%3Dwordlike",
        "https://example.invalid/?service_password=wordlike",
    ]:
        assert d.find(source) == []


def test_finds_userinfo_credentials() -> None:
    entities = d.find("Login at https://admin:hunter2@internal.example.com/dashboard")
    assert len(entities) == 1
    assert "admin:hunter2@" in entities[0].value


def test_finds_query_string_token() -> None:
    entities = d.find("See https://api.example.com/v1/report?api_key=abc123DEF456")
    assert len(entities) == 1


def test_finds_access_token_param() -> None:
    entities = d.find("https://example.com/callback?access_token=xyz789")
    assert len(entities) == 1


def test_plain_url_without_credentials_is_ignored() -> None:
    assert d.find("See https://example.com/docs/getting-started for details.") == []


def test_strips_trailing_punctuation() -> None:
    entities = d.find("(see https://user:pass@example.com/path).")
    assert entities[0].value.endswith("/path")


def test_finds_credentials_in_connection_strings_of_any_scheme() -> None:
    for url in (
        "postgres://admin:hunter2@db.internal:5432/app",
        "mongodb+srv://svc:p4ss@cluster0.example.net/db",
        "redis://:s3cr3t@cache:6379/0",  # password only, the usual Redis form
        "amqp://guest:guest@broker/vhost",
    ):
        entities = d.find(f"DATABASE_URL={url} (staging)")
        assert [e.value for e in entities] == [url]


def test_ignores_urls_without_credentials_whatever_the_scheme() -> None:
    assert d.find("see ftp://files.example.org/pub and postgres://admin@db/app") == []
