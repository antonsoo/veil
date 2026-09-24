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


def test_invalid_nanp_area_code_is_lower_confidence() -> None:
    # 012 is not a valid NANP area code (can't start with 0), but the
    # digit count still fits the generic international fallback, so it's
    # reported at reduced confidence rather than silently dropped.
    entities = d.find("012-555-0143")
    assert len(entities) == 1
    assert entities[0].confidence < 0.9


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
