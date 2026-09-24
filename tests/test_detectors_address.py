from veil.detectors.address import AddressDetector

d = AddressDetector()


def values(text: str) -> list[str]:
    return [e.value for e in d.find(text)]


def test_finds_simple_street_address() -> None:
    assert values("Ship to 123 Main Street, please.") == ["123 Main Street"]


def test_finds_address_with_abbreviated_suffix() -> None:
    assert values("456 Oak Ave") == ["456 Oak Ave"]


def test_finds_address_with_unit() -> None:
    entities = d.find("789 Elm Dr Apt 4B")
    assert entities[0].value == "789 Elm Dr Apt 4B"


def test_confidence_is_reduced_for_heuristic() -> None:
    entities = d.find("123 Main Street")
    assert entities[0].confidence <= 0.5


def test_no_match_without_number() -> None:
    assert values("Main Street is closed today.") == []
