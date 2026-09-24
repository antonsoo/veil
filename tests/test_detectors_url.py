from veil.detectors.url import UrlCredentialDetector

d = UrlCredentialDetector()


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
