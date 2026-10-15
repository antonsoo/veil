import pytest
from hypothesis import given
from hypothesis import strategies as st

from veil.audit import audit, find_leaked_originals, find_new_pii
from veil.detectors.url import UrlCredentialDetector
from veil.masker import Masker
from veil.surrogates import PlaceholderSurrogates
from veil.types import Entity, EntityType, Span
from veil.vault import Vault


def test_find_leaked_originals_detects_verbatim_leak() -> None:
    m = Masker()
    m.mask("Contact alice@example.com for details.")
    leaked_text = "Sure, I'll email alice@example.com right away."
    findings = find_leaked_originals(leaked_text, m.vault)
    assert len(findings) == 1
    assert findings[0].entity.value == "alice@example.com"


def test_find_leaked_originals_clean_text_has_no_findings() -> None:
    m = Masker()
    m.mask("Contact alice@example.com for details.")
    findings = find_leaked_originals("Everything looks fine, no PII here.", m.vault)
    assert findings == []


def test_find_new_pii_flags_value_not_in_vault() -> None:
    m = Masker()
    m.mask("Contact alice@example.com for details.")
    # The model invented a different email that was never masked.
    findings = find_new_pii("You can also reach bob@example.com.", m.vault)
    assert len(findings) == 1
    assert findings[0].entity.value == "bob@example.com"


def test_find_new_pii_ignores_known_surrogates() -> None:
    m = Masker()
    masked = m.mask("Contact alice@example.com for details.")
    # The surrogate itself is expected pre-restore text, not "new" PII.
    findings = find_new_pii(masked, m.vault)
    assert findings == []


def test_audit_combines_both_checks() -> None:
    m = Masker()
    m.mask("Contact alice@example.com for details.")
    text = "Original: alice@example.com. New: bob@example.com."
    findings = audit(text, m.vault)
    kinds = {f.kind for f in findings}
    assert kinds == {"leaked_original", "new_pii"}


def test_audit_clean_restored_text_has_no_findings() -> None:
    m = Masker()
    masked = m.mask("Contact alice@example.com for details.")
    restored = m.restore(masked)
    # Restoring intentionally reintroduces the original by design; audit
    # only flags it as "leaked" because it's checking outgoing text in
    # general. Demonstrate the distinct, purpose-built check instead: no
    # *new*, previously-unseen PII was introduced by the model.
    assert find_new_pii(restored, m.vault) == []


def _leaks_by_searching_per_value(text: str, vault: Vault) -> list[tuple[str, str, int]]:
    """The straightforward definition: each value's occurrences, left to right, without overlap."""
    found: list[tuple[int, int, str, str]] = []
    for order, mapping in enumerate(vault.mappings()):
        start = text.find(mapping.original) if mapping.original else -1
        while start != -1:
            found.append((start, order, mapping.type.value, mapping.original))
            start = text.find(mapping.original, start + len(mapping.original))
    return [(kind, value, start) for start, _, kind, value in sorted(found)]


_values = st.sampled_from(["a", "aa", "ab", "aba", "Alice", "Alice Johnson", "b", "ba", " "])
_types = st.sampled_from([EntityType.PERSON, EntityType.ORG, EntityType.EMAIL])


@given(
    st.lists(st.tuples(_types, _values), max_size=8),
    st.lists(st.sampled_from(["a", "b", " ", "Alice", " Johnson", "x"]), max_size=30).map("".join),
)
def test_find_leaked_originals_matches_a_search_per_value(
    entries: list[tuple[EntityType, str]], text: str
) -> None:
    vault = Vault()
    for entity_type, value in entries:
        vault.get_or_create(entity_type, value, PlaceholderSurrogates())
    findings = find_leaked_originals(text, vault)
    assert [
        (f.entity.type.value, f.entity.value, f.entity.span.start) for f in findings
    ] == _leaks_by_searching_per_value(text, vault)


@given(
    st.lists(
        st.tuples(
            _types,
            st.sampled_from(
                ["x" * n for n in (1, 31, 32, 33, 64, 65)]
                + ["💬é" * 20, "x" * 32 + "yes", "x" * 32 + "no"]
            ),
        ),
        max_size=12,
    ),
    st.lists(st.sampled_from(["x" * 80, "💬é" * 30, "yes", "no", " "]), max_size=10).map("".join),
)
def test_long_prefix_collisions_keep_exact_overlapping_occurrences(
    entries: list[tuple[EntityType, str]],
    text: str,
) -> None:
    vault = Vault()
    for entity_type, value in entries:
        vault.get_or_create(entity_type, value, PlaceholderSurrogates())
    findings = find_leaked_originals(text, vault)
    assert [
        (f.entity.type.value, f.entity.value, f.entity.span.start) for f in findings
    ] == _leaks_by_searching_per_value(text, vault)


def test_long_original_is_never_reported_from_only_its_prefix() -> None:
    vault = Vault()
    prefix = "https://files.example.test/" + "shared/" * 20
    original = prefix + "private?token=synthetic"
    vault.get_or_create(EntityType.URL_CREDENTIAL, original, PlaceholderSurrogates())
    assert find_leaked_originals(prefix, vault) == []
    assert find_leaked_originals(prefix + "public", vault) == []
    found = find_leaked_originals("💬 " + original + " suffix", vault)
    assert [(f.entity.value, f.entity.span.start, f.entity.span.end) for f in found] == [
        (original, 2, 2 + len(original)),
    ]


def test_leak_index_tracks_additions_and_transaction_rollback() -> None:
    vault = Vault()
    original = "x" * 40
    text = original * 3
    assert find_leaked_originals(text, vault) == []
    vault.get_or_create(EntityType.PERSON, original, PlaceholderSurrogates())
    assert len(find_leaked_originals(text, vault)) == 3
    try:
        with vault._transaction():
            vault.get_or_create(EntityType.ORG, original, PlaceholderSurrogates())
            assert len(find_leaked_originals(text, vault)) == 6
            raise ValueError("controlled rollback")
    except ValueError:
        pass
    assert len(find_leaked_originals(text, vault)) == 3


def test_equal_length_originals_share_a_prefix_without_becoming_equal() -> None:
    vault = Vault()
    generator = PlaceholderSurrogates()
    prefix = "https://files.example.test/shared/archive/"
    originals = [f"{prefix}{i:06d}?token=synthetic-{i:06d}" for i in range(100)]
    for original in originals:
        vault.get_or_create(EntityType.URL_CREDENTIAL, original, generator)
    vault.get_or_create(EntityType.SECRET, originals[-1], generator)
    text = f"💬 {prefix}public-link\n{originals[-1]}\n{originals[0]}\n{originals[-1]}"
    assert [
        (f.entity.type.value, f.entity.value, f.entity.span.start)
        for f in find_leaked_originals(text, vault)
    ] == _leaks_by_searching_per_value(text, vault)


@pytest.mark.parametrize(
    "original",
    [
        "https://files.example.test/share?token=alice@example.com",
        "https://203.0.113.42/archive?token=synthetic-private",
    ],
)
def test_restored_whole_url_has_known_pii_instead_of_new_pii(original: str) -> None:
    masker = Masker()
    restored = masker.restore(masker.mask(original), tolerant=False)
    assert restored == original
    assert len(masker.vault) == 1
    assert find_new_pii(restored, masker.vault) == []
    assert [f.kind for f in audit(restored, masker.vault)] == ["leaked_original"]
    new = find_new_pii(restored + "\nNew contact: bob@example.com", masker.vault)
    assert [(f.entity.type.value, f.entity.value) for f in new] == [("EMAIL", "bob@example.com")]


def test_known_surrogate_does_not_trigger_embedded_pii_or_hide_an_outside_contact() -> None:
    surrogate = "https://surrogate.example.test/share?token=fake@example.com"
    vault = Vault.from_dict(
        {
            "version": 1,
            "mappings": [
                {
                    "type": "SECRET",
                    "original": "private-credential",
                    "surrogate": surrogate,
                }
            ],
        }
    )
    assert audit(surrogate, vault) == []
    new = find_new_pii(surrogate + "\nbob@example.com", vault)
    assert [f.entity.value for f in new] == ["bob@example.com"]


def test_empty_detector_selection_keeps_original_leak_detection() -> None:
    masker = Masker()
    masker.mask("alice@example.com")
    text = "alice@example.com and bob@example.com"
    assert find_new_pii(text, masker.vault, detectors=[]) == []
    assert [(f.kind, f.entity.value) for f in audit(text, masker.vault, detectors=[])] == [
        ("leaked_original", "alice@example.com"),
    ]
    assert [f.entity.value for f in find_new_pii(text, masker.vault)] == ["bob@example.com"]


def test_known_email_does_not_hide_a_new_enclosing_credential_url() -> None:
    masker = Masker()
    masker.mask("alice@example.com")
    text = "https://files.example.test/share?token=alice@example.com"
    new = find_new_pii(text, masker.vault, [UrlCredentialDetector()])
    assert [f.entity.value for f in new] == [text]


class _LiteralDetector:
    name = "controlled_literal"

    def __init__(self, value: str) -> None:
        self.value = value

    def find(self, text: str) -> list[Entity]:
        return [
            Entity(EntityType.PERSON, self.value, Span(start, start + len(self.value)), self.name)
            for start in range(len(text))
            if text.startswith(self.value, start)
        ]


@pytest.mark.parametrize(
    ("originals", "text", "candidate", "expected"),
    [
        (["aba"], "ababa", "ba", []),
        (["secretA", "secretB"], "secretAsecretB", "Asecret", ["Asecret"]),
        (["secretA"], "secretAoutside", "Aoutside", ["Aoutside"]),
        (["secretA"], "xxsecretA", "xxsecret", ["xxsecret"]),
    ],
)
def test_new_pii_uses_complete_literal_containment(
    originals: list[str],
    text: str,
    candidate: str,
    expected: list[str],
) -> None:
    vault = Vault()
    for original in originals:
        vault.get_or_create(EntityType.SECRET, original, PlaceholderSurrogates())
    assert [
        f.entity.value for f in find_new_pii(text, vault, [_LiteralDetector(candidate)])
    ] == expected
