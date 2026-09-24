from veil.detectors.iban import IbanDetector, is_valid_iban

d = IbanDetector()

# Well-known published example IBANs (IBAN registry / Wikipedia examples),
# one of the few independently-checkable oracles available offline.
_VALID = [
    "GB29 NWBK 6016 1331 9268 19",  # UK example
    "DE89 3704 0044 0532 0130 00",  # Germany example
    "FR14 2004 1010 0505 0001 3M02 606",  # France example
]


def test_valid_examples_pass() -> None:
    for iban in _VALID:
        assert is_valid_iban(iban), iban


def test_wrong_checksum_fails() -> None:
    assert is_valid_iban("GB30 NWBK 6016 1331 9268 19") is False


def test_wrong_length_for_country_fails() -> None:
    assert is_valid_iban("DE89 3704 0044 0532 0130") is False  # too short for DE (22)


def test_unknown_country_fails() -> None:
    assert is_valid_iban("ZZ89 3704 0044 0532 0130 00") is False


def test_detector_finds_valid_iban_in_text() -> None:
    entities = d.find("Please wire to DE89 3704 0044 0532 0130 00 by Friday.")
    assert len(entities) == 1
    assert entities[0].value == "DE89 3704 0044 0532 0130 00"


def test_detector_ignores_invalid_lookalike() -> None:
    assert d.find("Reference code GB99 XXXX 0000 0000 0000 00") == []
