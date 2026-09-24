from veil.detectors.card import CardDetector, known_issuer, luhn_ok

d = CardDetector()


def test_luhn_known_valid_and_invalid() -> None:
    assert luhn_ok("4111111111111111") is True  # published Visa test number
    assert luhn_ok("4111111111111112") is False


def test_finds_visa_test_number_with_spaces() -> None:
    entities = d.find("Card on file: 4111 1111 1111 1111")
    assert len(entities) == 1
    assert entities[0].value == "4111 1111 1111 1111"
    assert entities[0].confidence > 0.9


def test_finds_amex_test_number() -> None:
    # 378282246310005 is Stripe/PayPal's published Amex test number.
    entities = d.find("Amex: 378282246310005")
    assert len(entities) == 1


def test_rejects_luhn_failing_number() -> None:
    assert d.find("1234 5678 9012 3456") == []


def test_known_issuer_ranges() -> None:
    assert known_issuer("4111111111111111") is True  # Visa
    assert known_issuer("5555555555554444") is True  # Mastercard
    assert known_issuer("378282246310005") is True  # Amex
    assert known_issuer("6011111111111117") is True  # Discover


def test_unknown_issuer_but_luhn_valid_is_lower_confidence() -> None:
    # A Luhn-valid number outside our documented issuer ranges is still
    # reported, just at reduced confidence.
    entities = d.find("9999999999999995")
    assert len(entities) == 1
    assert entities[0].confidence < 0.9
