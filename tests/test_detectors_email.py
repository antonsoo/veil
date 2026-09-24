from veil.detectors.email import EmailDetector

d = EmailDetector()


def values(text: str) -> list[str]:
    return [e.value for e in d.find(text)]


def test_finds_simple_email() -> None:
    assert values("Contact me at alice@example.com today.") == ["alice@example.com"]


def test_finds_plus_addressing_and_subdomain() -> None:
    assert values("alice+billing@mail.example.co.uk") == ["alice+billing@mail.example.co.uk"]


def test_finds_multiple_emails() -> None:
    assert values("a@x.com and b@y.org") == ["a@x.com", "b@y.org"]


def test_rejects_double_dot_in_local_or_domain() -> None:
    assert values("bad..name@example.com") == []
    assert values("name@example..com") == []


def test_rejects_no_tld() -> None:
    assert values("name@localhost") == []


def test_rejects_leading_trailing_dot_local() -> None:
    assert values(".name@example.com") == []


def test_does_not_match_inside_longer_token() -> None:
    # A URL query value shouldn't be swallowed past its real boundary.
    assert values("see notanemail@examplecomx") == []
