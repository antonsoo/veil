from veil.detectors.card import luhn_ok
from veil.surrogates import PlaceholderSurrogates, RealisticSurrogates, fake_card_number
from veil.types import EntityType


def test_placeholder_default_template() -> None:
    gen = PlaceholderSurrogates()
    assert gen.generate(EntityType.PERSON, "Alice Johnson", 1) == "⟨PERSON_1⟩"
    assert gen.generate(EntityType.EMAIL, "a@b.com", 2) == "⟨EMAIL_2⟩"


def test_placeholder_custom_template() -> None:
    gen = PlaceholderSurrogates(template="<<{type}_{n}>>")
    assert gen.generate(EntityType.EMAIL, "a@b.com", 2) == "<<EMAIL_2>>"


def test_realistic_person_names_are_deterministic() -> None:
    gen = RealisticSurrogates()
    first = gen.generate(EntityType.PERSON, "Real Name", 1)
    again = gen.generate(EntityType.PERSON, "Real Name", 1)
    assert first == again
    assert " " in first  # "First Last"


def test_realistic_email_uses_reserved_example_domain() -> None:
    gen = RealisticSurrogates()
    email = gen.generate(EntityType.EMAIL, "real@company.com", 1)
    assert email.endswith(("@example.com", "@example.org", "@example.net"))


def test_realistic_phone_is_in_555_0100_range() -> None:
    gen = RealisticSurrogates()
    for i in range(1, 20):
        phone = gen.generate(EntityType.PHONE, "real", i)
        area, exch, line = phone.split("-")
        assert exch == "555"
        assert line.startswith("01")


def test_realistic_card_passes_luhn() -> None:
    gen = RealisticSurrogates()
    for i in range(1, 10):
        card = gen.generate(EntityType.CARD, "4000000000000000", i)
        assert luhn_ok(card)
        assert len(card) in (15, 16)


def test_fake_card_number_helper_all_brands() -> None:
    for brand, length in (("visa", 16), ("mastercard", 16), ("amex", 15)):
        card = fake_card_number(1, brand)
        assert len(card) == length
        assert luhn_ok(card)


def test_realistic_falls_back_to_placeholder_for_unsupported_type() -> None:
    gen = RealisticSurrogates()
    surrogate = gen.generate(EntityType.SSN, "123-45-6789", 1)
    assert surrogate == "⟨SSN_1⟩"


def test_successive_indices_produce_distinct_names() -> None:
    gen = RealisticSurrogates()
    indices = range(1, 30)
    names = {gen.generate(EntityType.PERSON, f"real{i}", i) for i in indices}
    assert len(names) == len(indices)
