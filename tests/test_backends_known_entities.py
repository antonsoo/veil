from veil.backends.known_entities import KnownEntitiesBackend


def test_finds_person_case_insensitively() -> None:
    backend = KnownEntitiesBackend(persons=["Alice Johnson"])
    entities = backend.find("i spoke with alice johnson yesterday")
    assert len(entities) == 1
    assert entities[0].value == "alice johnson"
    assert entities[0].type.value == "PERSON"


def test_longer_entry_wins_over_substring() -> None:
    backend = KnownEntitiesBackend(persons=["Alice", "Alice Johnson"])
    entities = backend.find("Alice Johnson called.")
    assert len(entities) == 1
    assert entities[0].value == "Alice Johnson"


def test_respects_word_boundaries() -> None:
    backend = KnownEntitiesBackend(persons=["Al"])
    assert backend.find("Alice was here") == []


def test_org_and_location_types() -> None:
    backend = KnownEntitiesBackend(orgs=["Acme Corp"], locations=["Springfield"])
    entities = backend.find("Acme Corp is based in Springfield.")
    types = {e.type.value for e in entities}
    assert types == {"ORG", "LOCATION"}


def test_empty_backend_finds_nothing() -> None:
    backend = KnownEntitiesBackend()
    assert backend.find("Alice Johnson called from Acme Corp.") == []
