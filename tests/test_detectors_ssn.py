from veil.detectors.ssn import SsnDetector, is_valid_ssn

d = SsnDetector()


def test_valid_structural_ssn() -> None:
    assert is_valid_ssn("123", "45", "6789") is True


def test_rejects_area_000_666_or_900plus() -> None:
    assert is_valid_ssn("000", "45", "6789") is False
    assert is_valid_ssn("666", "45", "6789") is False
    assert is_valid_ssn("900", "45", "6789") is False


def test_rejects_group_00_or_serial_0000() -> None:
    assert is_valid_ssn("123", "00", "6789") is False
    assert is_valid_ssn("123", "45", "0000") is False


def test_finds_dashed_ssn_in_text() -> None:
    entities = d.find("SSN on file: 123-45-6789.")
    assert len(entities) == 1
    assert entities[0].value == "123-45-6789"


def test_ignores_bare_9_digit_number_without_context() -> None:
    assert d.find("Order total was 123456789 cents.") == []


def test_finds_bare_digits_with_ssn_context() -> None:
    entities = d.find("SSN 123456789 on file")
    assert len(entities) == 1


def test_rejects_invalid_area_even_with_dashes() -> None:
    assert d.find("Ref 000-45-6789") == []


def test_ignores_zip_plus_four() -> None:
    # 5 digits + dash + 4 digits parses as area(3)+group(2)+serial(4) if
    # separators aren't required to be consistent at both gaps.
    assert d.find("Ship to ZIP 22156-7224.") == []


def test_ignores_space_separated_zip_plus_four_shape() -> None:
    assert d.find("Ship to ZIP 22156 7224.") == []


def test_finds_ssn_with_space_separators() -> None:
    entities = d.find("SSN on file: 123 45 6789.")
    assert len(entities) == 1
    assert entities[0].value == "123 45 6789"


def test_rejects_mixed_separators() -> None:
    # A dash before the group but a space before the serial (or vice
    # versa) isn't how a real SSN is written.
    assert d.find("Ref 123-45 6789") == []
