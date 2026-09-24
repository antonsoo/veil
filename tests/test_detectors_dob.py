from veil.detectors.dob import DobDetector

d = DobDetector()


def values(text: str) -> list[str]:
    return [e.value for e in d.find(text)]


def test_finds_date_near_dob_label() -> None:
    assert values("DOB: 03/14/1990") == ["03/14/1990"]


def test_finds_date_near_born_on() -> None:
    assert values("Patient was born on 1990-03-14 in Ohio.") == ["1990-03-14"]


def test_finds_month_name_date() -> None:
    assert values("Date of birth: March 14, 1990") == ["March 14, 1990"]


def test_ignores_date_without_birth_context() -> None:
    assert values("Invoice date: 03/14/1990") == []


def test_ignores_far_away_date() -> None:
    # The date is nowhere near the DOB keyword.
    text = "DOB" + " " * 200 + "03/14/1990"
    assert values(text) == []
