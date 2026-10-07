from veil.restore import restore_tolerant
from veil.vault import Vault


def test_tolerant_restore_does_not_choose_between_conflicting_identities() -> None:
    vault = Vault.from_dict(
        {
            "mappings": [
                {"type": "PERSON", "original": "Alice", "surrogate": "FAKE PERSON"},
                {"type": "PERSON", "original": "Bob", "surrogate": "fake person"},
            ]
        }
    )
    assert (
        restore_tolerant("FAKE PERSON, fake person, Fake Person", vault)
        == "Alice, Bob, Fake Person"
    )


def test_unicode_casefold_expansions_match_whole_codepoints() -> None:
    vault = Vault.from_dict(
        {
            "mappings": [
                {"type": "PERSON", "original": "Private person", "surrogate": "Straße Alias"},
            ]
        }
    )
    assert restore_tolerant("STRASSE ALIAS", vault) == "Private person"
    assert restore_tolerant("STRASSE ALIASES", vault) == "STRASSE ALIASES"


def test_ambiguous_casefold_does_not_override_an_exact_match() -> None:
    vault = Vault.from_dict(
        {
            "mappings": [
                {"type": "PERSON", "original": "Alice", "surrogate": "Straße Alias"},
                {"type": "PERSON", "original": "Bob", "surrogate": "Strasse Alias"},
            ]
        }
    )
    assert restore_tolerant("STRASSE ALIAS", vault) == "STRASSE ALIAS"
    assert restore_tolerant("Straße Alias", vault) == "Alice"
