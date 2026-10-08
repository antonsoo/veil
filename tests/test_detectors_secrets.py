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


def _pem(label: str, body: str, *, end: bool = True) -> str:
    # Built at runtime so no literal key header sits in the repo for secret
    # scanners to flag.
    dashes = "-" * 5
    text = f"{dashes}BEGIN {label}{dashes}\n{body}"
    return f"{text}\n{dashes}END {label}{dashes}" if end else text


def test_masks_a_pem_private_key_as_one_block() -> None:
    key = _pem("RSA " + "PRIVATE KEY", "MIIEpAIBAAKCAQEA7bq98F2kTL\nkdjf83hf==")
    assert values(f"here it is:\n{key}\nthanks") == [key]
    pgp = _pem("PGP " + "PRIVATE KEY BLOCK", "lQOYBF")
    assert values(pgp) == [pgp]


def test_masks_a_truncated_private_key_through_its_body() -> None:
    key = _pem(
        "OPENSSH " + "PRIVATE KEY",
        "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ\nAAAAAAAB",
        end=False,
    )
    assert values(f"pasted: {key}") == [key]


def test_leaves_public_keys_and_certificates_alone() -> None:
    assert values(_pem("PUBLIC KEY", "MFkwEwYH")) == []


# What 0.4.4 masked as secrets in real logs and source trees (studies/real-text).


def test_paths_and_names_are_not_secrets() -> None:
    for text in (
        "NameSystem.allocateBlock: /user/root/rand/_temporary/_task_200811092030_0001_m_000742_0/part",
        "--jsonfile=/logs/artifacts/junit_20261005-092148.stdout",
        "=== RUN   TestSchedulerPerf/SchedulingPodAffinity/5000Nodes_5000Pods",
        "ok  k8s.io/kubernetes/pkg/apis/discovery/v1beta1 0.02s",
        "Failed to renew lease for [DFSClient_NONMAPREDUCE_1537864556_1] for 30 seconds",
        "wsgi.server [req-d81279b2-d9df-48b7-9c36-edab3801c067 113d3a99c3da401fbd62cc2caa5b96d2]",
        "GET /v2/54fadb412c4e40cdbaed9335e4c35a9e/servers/detail HTTP/1.1",
        "def test_HTTP_302_TOO_MANY_REDIRECTS(self, httpbin):",
        "path /usr/lib/jvm/java-7-openjdk-amd64/jre/bin",
    ):
        assert values(text) == [], text


def test_random_tokens_are_still_found_beside_them() -> None:
    assert values("h1:FRsXN1f5AsAjCGJKqEizvkpNtU+EGNCLh3NxZ/8L+MA=") == [
        "FRsXN1f5AsAjCGJKqEizvkpNtU+EGNCLh3NxZ/8L+MA"
    ]
    assert values("Authorization: Bearer 2BPb1rsD95o5Jm5SqWs1KteqdnynnB7jkTE") == [
        "2BPb1rsD95o5Jm5SqWs1KteqdnynnB7jkTE"
    ]
    # 20 characters: too short to reach 4.0 bits a character, and found now.
    assert values("token k3jx9q2mzv7w1p8ybn4t") == ["k3jx9q2mzv7w1p8ybn4t"]


def test_most_random_tokens_of_twenty_characters_are_found() -> None:
    import random
    import string

    rng = random.Random(7)
    for alphabet in (string.ascii_lowercase + string.digits, string.ascii_letters + string.digits):
        tokens = ["".join(rng.choice(alphabet) for _ in range(20)) for _ in range(500)]
        found = sum(values(f"token {token} end") == [token] for token in tokens)
        assert found >= 450, (alphabet[:8], found)  # 0.4.4 found between 100 and 320
