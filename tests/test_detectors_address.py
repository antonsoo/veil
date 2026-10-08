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


# Shapes from OpenStreetMap addr: tags in New York, Chicago and Toronto.


def test_finds_numbered_streets() -> None:
    assert values("Deliver to 38 West 32nd Street, New York.") == ["38 West 32nd Street"]
    assert values("The shop at 484 9th Avenue is closed.") == ["484 9th Avenue"]


def test_takes_the_compass_point_after_the_suffix() -> None:
    assert values("424 Park Avenue South, New York") == ["424 Park Avenue South"]
    assert values("12 Queen St W, Toronto") == ["12 Queen St W"]
    assert values("332-334 Queen Street West") == ["332-334 Queen Street West"]
    assert values("turn at 5 Oak Street E of the river") == ["5 Oak Street"]
