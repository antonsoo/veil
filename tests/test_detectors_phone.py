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


# The cases below are shapes from OpenStreetMap phone tags that 0.4.4 missed
# (studies/real-text): the digits are made up, the grouping is each country's.


def test_international_numbers_are_found_however_the_digits_are_grouped() -> None:
    for number in (
        "+33 1 23 45 67 89",  # France: one digit, then pairs
        "+49 30 12345678",  # Germany: eight digits in one group
        "+81 3-1234-5678",  # Japan: a one-digit area code
        "+61 2 9374 4000",  # Australia
        "+353 1 679 1122",  # Ireland
        "+39 06 6874848",  # Italy keeps the zero
        "+91 98765 43210",  # India: five and five
        "+44 (0)20 7946 0958",  # the trunk zero some print for domestic callers
        "+49 30 / 123 456-0",
        "+33.1.23.45.67.89",
    ):
        assert values(f"Call {number} today.") == [number], number


def test_a_plus_and_digits_need_a_real_calling_code_and_length() -> None:
    assert values("+999 123 456 789") == []  # no such calling code
    assert values("+10 2026 10 08") == []  # North America, but nine digits
    assert values("+33 1 23 45") == []  # France, but too short


def test_digits_after_a_number_are_not_part_of_it() -> None:
    assert values("call +1 212 555 0134 2026 times") == ["+1 212 555 0134"]
    assert values("+1 212 555 0134 2026-10-08") == ["+1 212 555 0134"]
    assert values("+1-416-555-0134x5") == ["+1-416-555-0134"]


def test_signed_decimals_and_changelog_lines_are_not_numbers() -> None:
    # Go prints a monotonic clock reading as m=+32.035815963.
    assert values('at="2026-09-20 22:09:08.515982131 +0000 UTC m=+32.035815963"') == []
    assert values("+4.13.3 / 2015-08-02") == []


def test_an_international_number_outranks_the_ssn_shape_inside_it() -> None:
    assert values("+33 142 78 2350") == ["+33 142 78 2350"]
    assert values("ssn 142-78-2350") == []
