"""Surrogate generation: turning a detected value into a stand-in for the LLM.

Two styles, both documented with their trade-off:

- :class:`PlaceholderSurrogates` emits tokens like ``⟨PERSON_1⟩``. This is
  the robust default: the model cannot mistake a placeholder for a real
  value, and restoration only has to find the exact token back. The
  trade-off is that placeholders visibly interrupt the model's prose ("Dear
  ⟨PERSON_1⟩, your order ⟨CARD_1⟩ ...") which can make responses read
  stiffly and, in rare cases, confuses a model into commenting on the
  bracket syntax itself.
- :class:`RealisticSurrogates` emits fakes that are the right *shape*
  (a plausible name, an `example.com` email, a 555-0100-range phone
  number, a Luhn-valid test card) so the model's prose stays natural and
  it can do arithmetic/formatting on the value as if it were real. The
  trade-off is weaker guarantees: a fake can coincidentally collide with
  something the model says on its own, format-preserving fakes leak
  *structure* (e.g. a fake IBAN still reveals the real one's country), and
  a careless restore step could mistake an incidental example.com address
  the model invented for a surrogate.

Both generators are consistent within a :class:`~veil.vault.Vault`: the
vault, not the generator, is what remembers "this original already has a
surrogate" (see :meth:`veil.vault.Vault.get_or_create`). The generator's
job is only to mint a *new* surrogate the first time a value is seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from veil.detectors.card import luhn_ok
from veil.types import EntityType

_FIRST_NAMES = (
    "Avery", "Blair", "Casey", "Dana", "Ellis", "Frankie", "Greer", "Harper",
    "Iris", "Jules", "Kai", "Lane", "Morgan", "Noor", "Oakley", "Parker",
    "Quinn", "Reese", "Sage", "Tatum", "Uma", "Val", "Wren", "Yuki",
)  # fmt: skip
_LAST_NAMES = (
    "Alder", "Brooks", "Castillo", "Delgado", "Ellison", "Farrow", "Grant",
    "Haas", "Ibarra", "Jansen", "Kwan", "Lindqvist", "Moreau", "Nakamura",
    "Okafor", "Petrov", "Quaye", "Rousseau", "Salazar", "Tanaka", "Ueda",
    "Vance", "Wu", "Yilmaz",
)  # fmt: skip
_ORG_WORDS = (
    "Acme", "Brightline", "Cobalt", "Driftwood", "Evergate", "Fulcrum",
    "Gantry", "Hearth", "Ironwood", "Juniper", "Kestrel", "Lattice",
)  # fmt: skip
_ORG_SUFFIXES = ("Inc.", "LLC", "Co.", "Group", "Partners", "Labs")

# RFC 2606 reserved for documentation/examples; will never resolve to a
# real mailbox that receives mail.
_EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net")

# NANP reserves area-code-555-01XX (100 numbers per area code) for fiction
# (see NANPA / ATIS guidelines commonly cited as "555-0100 through
# 555-0199"). We cycle through a handful of plausible US area codes.
_FAKE_AREA_CODES = ("202", "212", "312", "415", "512", "617", "702", "917")

# Published test card prefixes that are documented as never issued to real
# cardholders (Visa/Mastercard/Amex test-number ranges used by payment
# processors' own sandboxes). We generate the trailing digits and append a
# real Luhn check digit so `luhn_ok()` on the output is always true.
_FAKE_CARD_PREFIXES = {
    "visa": "400000",
    "mastercard": "510000",
    "amex": "370000",
}


def _luhn_check_digit(partial: str) -> str:
    # Append a placeholder, compute what check digit makes it valid.
    for digit in "0123456789":
        if luhn_ok(partial + digit):
            return digit
    raise AssertionError("unreachable: a Luhn check digit always exists")  # pragma: no cover


def fake_card_number(index: int, brand: str = "visa") -> str:
    prefix = _FAKE_CARD_PREFIXES[brand]
    body_len = (15 if brand == "amex" else 16) - len(prefix) - 1
    body = str(index % (10**body_len)).zfill(body_len)
    partial = prefix + body
    return partial + _luhn_check_digit(partial)


@runtime_checkable
class SurrogateGenerator(Protocol):
    """Mints a fresh surrogate for a first-seen value of a given type."""

    def generate(self, entity_type: EntityType, original: str, index: int) -> str: ...


@dataclass
class PlaceholderSurrogates:
    """``⟨TYPE_N⟩``-style tokens. ``template`` takes ``{type}`` and ``{n}``."""

    template: str = "⟨{type}_{n}⟩"

    def generate(self, entity_type: EntityType, original: str, index: int) -> str:
        return self.template.format(type=entity_type.value, n=index)


@dataclass
class RealisticSurrogates:
    """Format-preserving fakes; falls back to a placeholder for types with
    no realistic generator defined (SSN, IBAN, IP, secrets, DOB, address,
    URL-credential) since a "realistic" fake there is either meaningless
    (an IP has no fictional-reserved block for this purpose) or actively
    unsafe (a fake secret that *looks* like a real key format).
    """

    fallback: PlaceholderSurrogates = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.fallback is None:
            self.fallback = PlaceholderSurrogates()

    def generate(self, entity_type: EntityType, original: str, index: int) -> str:
        if entity_type is EntityType.PERSON:
            first = _FIRST_NAMES[index % len(_FIRST_NAMES)]
            last = _LAST_NAMES[(index // len(_FIRST_NAMES)) % len(_LAST_NAMES)]
            return f"{first} {last}"
        if entity_type is EntityType.ORG:
            word = _ORG_WORDS[index % len(_ORG_WORDS)]
            suffix = _ORG_SUFFIXES[(index // len(_ORG_WORDS)) % len(_ORG_SUFFIXES)]
            return f"{word} {suffix}"
        if entity_type is EntityType.EMAIL:
            local = f"user{index}"
            domain = _EXAMPLE_DOMAINS[index % len(_EXAMPLE_DOMAINS)]
            return f"{local}@{domain}"
        if entity_type is EntityType.PHONE:
            area = _FAKE_AREA_CODES[(index // 100) % len(_FAKE_AREA_CODES)]
            # NANP reserves 555-0100..555-0199 in every area code for
            # fiction (film/TV, docs, tests); cycle through it.
            line = index % 100
            return f"{area}-555-01{line:02d}"
        if entity_type is EntityType.CARD:
            brands = ("visa", "mastercard", "amex")
            return fake_card_number(index, brands[index % len(brands)])
        return self.fallback.generate(entity_type, original, index)
