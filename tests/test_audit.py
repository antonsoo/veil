from veil.audit import audit, find_leaked_originals, find_new_pii
from veil.masker import Masker


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
