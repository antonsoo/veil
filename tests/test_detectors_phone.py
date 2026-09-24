from veil.detectors.phone import PhoneDetector

d = PhoneDetector()


def values(text: str) -> list[str]:
    return [e.value for e in d.find(text)]


def test_finds_e164() -> None:
    assert values("call +12025550143 now") == ["+12025550143"]


def test_finds_e164_with_separators() -> None:
    assert values("call +1 202 555 0143 now") == ["+1 202 555 0143"]


def test_finds_nanp_with_parens() -> None:
    assert values("Reach us at (202) 555-0143.") == ["(202) 555-0143"]


def test_finds_nanp_dashed() -> None:
    assert values("202-555-0143") == ["202-555-0143"]


def test_invalid_nanp_area_code_is_rejected() -> None:
    # 012 is not a valid NANP area code (can't start with 0). There is no
    # generic separator-only fallback bucket anymore (see the module
    # docstring for why), so this is dropped entirely rather than
    # reported at reduced confidence.
    assert d.find("012-555-0143") == []


def test_rejects_short_number() -> None:
    assert values("12-34") == []


def test_prose_with_no_phone_number_matches_nothing() -> None:
    assert values("Invoice #4471 was paid on time.") == []


def test_does_not_flag_ipv4_address_as_phone() -> None:
    # A dot-separated IPv4 address is structurally identical to a
    # dot-separated phone number; defer to the dedicated IP detector.
    assert values("The affected host is 190.229.140.23 today.") == []


def test_still_finds_genuine_dot_separated_phone() -> None:
    assert values("Call 202.555.0143 for support.") == ["202.555.0143"]


# --- Regression coverage for the over-masking bug: an ISO date and an
# order number were both flagged as phone numbers (see the module
# docstring and CHANGELOG). ---------------------------------------------


def test_ignores_iso_date() -> None:
    assert values("Order #4417-2291 shipped on 2026-09-21 for $1,249.99.") == []


def test_ignores_dd_mm_yyyy_date() -> None:
    assert values("Delivered on 21-09-2026 as promised.") == []


def test_ignores_time_of_day() -> None:
    assert values("The call is scheduled for 14:30:00 sharp.") == []


def test_ignores_version_string() -> None:
    assert values("Upgraded to version 2.14.3 last night.") == []


def test_ignores_order_number_with_hash() -> None:
    assert values("Please refund order #4417-2291 in full.") == []


def test_ignores_order_number_word_context_even_if_nanp_shaped() -> None:
    # Digits alone are valid-looking NANP (202-555-0143), but "order"
    # right before it means this is an order number, not a phone number.
    assert values("Your order 202-555-0143 has shipped.") == []


def test_ignores_ticket_number_with_hash_even_if_nanp_shaped() -> None:
    assert values("Ticket #202-555-0143 needs review.") == []


def test_ignores_invoice_id() -> None:
    assert values("See invoice INV-202-555-0199 for details.") == []


def test_ignores_zip_plus_four() -> None:
    assert values("Ship to ZIP 94103-1234 please.") == []


def test_ignores_ups_tracking_number() -> None:
    assert values("Tracking number 1Z999AA10123456784 is out for delivery.") == []


def test_ignores_price() -> None:
    assert values("The total came to $1,249.99 after tax.") == []


def test_ignores_room_number() -> None:
    assert values("Meet us in Room 204 at noon.") == []


def test_ignores_build_number() -> None:
    assert values("Regression only reproduces on build 2026.09.21.1453.") == []
