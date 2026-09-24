from veil.detectors.secrets import SecretDetector, shannon_entropy

d = SecretDetector()


def values(text: str) -> list[str]:
    return [e.value for e in d.find(text)]


def test_finds_aws_access_key() -> None:
    assert values("key=AKIAIOSFODNN7EXAMPLE") == ["AKIAIOSFODNN7EXAMPLE"]


def test_finds_github_classic_pat() -> None:
    token = "ghp_" + "a" * 36
    assert values(f"token: {token}") == [token]


def test_finds_github_fine_grained_pat() -> None:
    token = "github_pat_" + "a1B2" * 10
    assert token in values(f"token: {token}")


def test_finds_slack_token() -> None:
    token = "xoxb-" + "1234567890" + "-" + "abcdefghijklmnop"
    assert values(f"slack {token}") == [token]


def test_finds_stripe_live_key() -> None:
    token = "sk_live_" + "a" * 24
    assert values(token) == [token]


def test_finds_anthropic_key() -> None:
    token = "sk-ant-" + "a" * 30
    assert values(token) == [token]


def test_openai_pattern_does_not_shadow_anthropic() -> None:
    # sk-ant-... should be classified via the more specific anthropic
    # pattern, not double-counted by the generic sk- pattern.
    token = "sk-ant-" + "a" * 30
    entities = d.find(token)
    assert len(entities) == 1
    assert entities[0].detector == "secret:anthropic_key"


def test_entropy_helper_low_for_repeated_char() -> None:
    assert shannon_entropy("aaaaaaaaaa") == 0.0


def test_entropy_helper_high_for_random_looking_string() -> None:
    assert shannon_entropy("aZ3kQ9mP1xR7vL2n") > 3.0


def test_high_entropy_heuristic_flags_random_token() -> None:
    # A base62-ish random-looking token with digits, no recognized prefix.
    entities = d.find("secret=aZ3kQ9mP1xR7vL2nB8wT4dY6")
    assert len(entities) == 1
    assert entities[0].detector == "secret:high_entropy"
    assert entities[0].confidence < 0.9  # heuristic, not a known format


def test_plain_prose_has_no_false_positive() -> None:
    assert values("The quick brown fox jumps over the lazy dog.") == []


def test_hex_hash_not_flagged_by_entropy_heuristic() -> None:
    # A pure-hex string (e.g. a git commit or content hash) is common and
    # not a secret by itself; the heuristic deliberately skips it.
    sha = "d41d8cd98f00b204e9800998ecf8427e12345678"
    assert values(f"commit {sha}") == []
