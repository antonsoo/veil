from veil.backends.known_entities import KnownEntitiesBackend
from veil.masker import Masker
from veil.surrogates import RealisticSurrogates
from veil.types import EntityType


def test_mask_replaces_detected_entities() -> None:
    m = Masker()
    text = "Email alice@example.com about invoice #4471."
    masked = m.mask(text)
    assert "alice@example.com" not in masked
    assert "invoice #4471" in masked  # untouched, not PII


def test_mask_is_consistent_for_repeated_value() -> None:
    m = Masker()
    text = "alice@example.com wrote to alice@example.com again."
    masked = m.mask(text)
    tokens = [w for w in masked.split() if w.startswith("⟨")]
    assert len(set(tokens)) == 1  # same surrogate both times


def test_mask_then_restore_round_trips() -> None:
    m = Masker()
    text = "Contact alice@example.com or +1 202-555-0143."
    masked = m.mask(text)
    assert m.restore(masked) == text


def test_overlap_resolution_prefers_longer_span_on_confidence_tie() -> None:
    # "alice" (a known-entities org, confidence 1.0) is a substring of the
    # email "alice@example.com" (also confidence 1.0). The full email span
    # is longer, so it should win and leave one merged surrogate rather
    # than a mangled partial replacement.
    backend = KnownEntitiesBackend(orgs=["alice"])
    m = Masker(name_backends=[backend])
    masked = m.mask("Reach alice@example.com for support.")
    assert masked.count("⟨") == 1
    assert m.restore(masked) == "Reach alice@example.com for support."


def test_known_entities_backend_feeds_masker() -> None:
    backend = KnownEntitiesBackend(persons=["Alice Johnson"], locations=["Springfield"])
    m = Masker(name_backends=[backend])
    masked = m.mask("Alice Johnson moved to Springfield last year.")
    assert "Alice Johnson" not in masked
    assert "Springfield" not in masked
    assert m.restore(masked) == "Alice Johnson moved to Springfield last year."


def test_realistic_surrogates_keep_prose_natural() -> None:
    m = Masker(surrogate_generator=RealisticSurrogates())
    masked = m.mask("Email alice@example.org today.")
    assert "@" in masked  # still looks like an email
    assert "alice@example.org" not in masked


def test_vault_records_entity_type() -> None:
    m = Masker()
    m.mask("alice@example.com")
    mapping = m.vault.lookup_original(EntityType.EMAIL, "alice@example.com")
    assert mapping is not None
    assert mapping.type is EntityType.EMAIL


def test_empty_text_is_a_noop() -> None:
    m = Masker()
    assert m.mask("") == ""
    assert m.restore("") == ""


def test_no_pii_present_is_unchanged() -> None:
    m = Masker()
    text = "The weather today is mild with a light breeze."
    assert m.mask(text) == text
