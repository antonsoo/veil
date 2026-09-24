#!/usr/bin/env python3
"""Generate a synthetic, labelled PII corpus for evaluating veil's detectors.

Every value in this corpus is fabricated: fake names, `example.com`
emails, NANP 555-01xx phone numbers, `veil.surrogates.fake_card_number`
test-range card numbers, mod-97-valid but never-issued IBANs, and
structurally-valid-but-random SSNs/IPs/secrets. **None of it is real
personal data.** The corpus is regenerated deterministically from a fixed
seed so results in the README are reproducible.

Only entity types the built-in regex detectors actually claim to find are
labelled (email, phone, card, IBAN, SSN, IPv4/IPv6, URL-credential,
secret, DOB, address). Person names appear in the generated text for
realism but are intentionally *not* labelled ground truth: name detection
is backend-driven (see `veil.backends`) and evaluated separately, not by
this regex-detector benchmark.

Usage:
    uv run python scripts/generate_corpus.py > benchmarks/corpus.jsonl
"""

from __future__ import annotations

import json
import random
import string
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from veil.surrogates import fake_card_number  # noqa: E402

SEED = 42

FIRST_NAMES = [
    "Jordan", "Casey", "Morgan", "Riley", "Taylor", "Avery", "Quinn", "Reese",
    "Dana", "Skyler", "Rowan", "Emerson", "Kai", "Finley", "Harper", "Sage",
]  # fmt: skip
LAST_NAMES = [
    "Alvarez", "Brennan", "Chen", "Duarte", "Eriksson", "Farrow", "Gutierrez",
    "Haas", "Ibori", "Jansen", "Kowalski", "Larsen", "Mensah", "Novak",
    "O'Brien", "Petrova",
]  # fmt: skip
DOMAINS = ["example.com", "example.org", "example.net"]
AREA_CODES = ["202", "212", "312", "415", "512", "617", "702", "917"]
STREETS = ["Maple Street", "Oak Avenue", "Elm Drive", "Cedar Lane", "Pine Court", "Birch Road"]
CARD_BRANDS = ["visa", "mastercard", "amex"]
IBAN_SPECS = [("DE", 18), ("GB", 18), ("FR", 23), ("NL", 14), ("ES", 20)]
FILLER_SENTENCES = [
    "Thanks for reaching out.",
    "We appreciate your patience while we look into this.",
    "Let us know if you have any other questions.",
    "This has been a recurring issue for the past week.",
    "The weather has been unusually mild this month.",
    "Our team meets every Tuesday to review open items.",
    "Please find the attached summary for your records.",
    "I'll follow up again if anything changes.",
]


def iban_check_digits(country: str, bban: str) -> str:
    rearranged = bban + country + "00"
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    remainder = int(digits) % 97
    return f"{98 - remainder:02d}"


class TextBuilder:
    """Accumulates text while tracking the exact span of each inserted
    entity, so ground-truth offsets never have to be recomputed by hand.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._length = 0
        self.entities: list[dict[str, Any]] = []

    def text(self, s: str) -> TextBuilder:
        self._parts.append(s)
        self._length += len(s)
        return self

    def entity(self, value: str, etype: str) -> TextBuilder:
        start = self._length
        self._parts.append(value)
        self._length += len(value)
        self.entities.append({"type": etype, "value": value, "start": start, "end": self._length})
        return self

    def build(self) -> str:
        return "".join(self._parts)


def make_email(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES).lower()}.{rng.choice(LAST_NAMES).lower()}@{rng.choice(DOMAINS)}"


def make_phone(rng: random.Random) -> str:
    return f"{rng.choice(AREA_CODES)}-555-01{rng.randint(0, 99):02d}"


def make_ssn(rng: random.Random) -> str:
    area = rng.randint(1, 899)
    while area == 666:
        area = rng.randint(1, 899)
    return f"{area:03d}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}"


def make_card(rng: random.Random, index: int) -> str:
    return fake_card_number(index, rng.choice(CARD_BRANDS))


def make_iban(rng: random.Random) -> str:
    country, bban_len = rng.choice(IBAN_SPECS)
    bban = "".join(str(rng.randint(0, 9)) for _ in range(bban_len))
    return f"{country}{iban_check_digits(country, bban)}{bban}"


def make_ipv4(rng: random.Random) -> str:
    return ".".join(str(rng.randint(1, 254)) for _ in range(4))


def make_secret(rng: random.Random) -> str:
    body = "".join(rng.choices(string.ascii_letters + string.digits, k=36))
    return f"ghp_{body}"


def make_dob(rng: random.Random) -> str:
    return f"{rng.randint(1, 12):02d}/{rng.randint(1, 28):02d}/{rng.randint(1950, 2005)}"


def make_address(rng: random.Random) -> str:
    return f"{rng.randint(1, 9999)} {rng.choice(STREETS)}"


def make_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def support_ticket(rng: random.Random, i: int) -> TextBuilder:
    b = TextBuilder()
    name = make_name(rng)
    b.text("Subject: Account access issue\n\nHi team,\n\nMy name is ")
    b.text(name)
    b.text(" and I'm having trouble logging in. My account email is ")
    b.entity(make_email(rng), "EMAIL")
    b.text(". You can reach me at ")
    b.entity(make_phone(rng), "PHONE")
    b.text(" if a call is easier. ")
    b.text(rng.choice(FILLER_SENTENCES))
    b.text(" I tried to update the card on file (")
    b.entity(make_card(rng, i), "CARD")
    b.text(") but the charge failed. My IP was ")
    b.entity(make_ipv4(rng), "IPV4")
    b.text(" at the time, in case that helps your logs. ")
    b.text(rng.choice(FILLER_SENTENCES))
    b.text(f"\n\nThanks,\n{name}\n")
    return b


def billing_dispute(rng: random.Random, i: int) -> TextBuilder:
    b = TextBuilder()
    name = make_name(rng)
    b.text(f"Hello, this is {name}. I'd like to dispute a charge on my account.\n\n")
    b.text("For verification: DOB ")
    b.entity(make_dob(rng), "DOB")
    b.text(", SSN ")
    b.entity(make_ssn(rng), "SSN")
    b.text(". Please wire any refund to IBAN ")
    b.entity(make_iban(rng), "IBAN")
    b.text(". ")
    b.text(rng.choice(FILLER_SENTENCES))
    b.text(" Ship any replacement to ")
    b.entity(make_address(rng), "ADDRESS")
    b.text(". ")
    b.text(rng.choice(FILLER_SENTENCES))
    return b


def clinical_note(rng: random.Random, i: int) -> TextBuilder:
    b = TextBuilder()
    name = make_name(rng)
    b.text(f"Patient: {name}\n")
    b.text("Date of birth: ")
    b.entity(make_dob(rng), "DOB")
    b.text("\nContact email on file: ")
    b.entity(make_email(rng), "EMAIL")
    b.text(f"\n\nNotes: patient was born on the date above and presents for a routine follow-up. ")
    b.text(rng.choice(FILLER_SENTENCES))
    b.text(" Emergency contact phone: ")
    b.entity(make_phone(rng), "PHONE")
    b.text(". ")
    b.text(rng.choice(FILLER_SENTENCES))
    return b


def devops_incident_email(rng: random.Random, i: int) -> TextBuilder:
    b = TextBuilder()
    b.text("Subject: Credential rotation needed\n\n")
    b.text("Hi, the following key was committed by mistake and needs rotating: ")
    b.entity(make_secret(rng), "SECRET")
    b.text(". The affected host is ")
    b.entity(make_ipv4(rng), "IPV4")
    b.text(". Also please update the on-call email to ")
    b.entity(make_email(rng), "EMAIL")
    b.text(". ")
    b.text(rng.choice(FILLER_SENTENCES))
    b.text(" ")
    b.text(rng.choice(FILLER_SENTENCES))
    return b


def clean_negative(rng: random.Random, i: int) -> TextBuilder:
    """No PII at all: a pure precision/false-positive check."""
    b = TextBuilder()
    b.text(" ".join(rng.sample(FILLER_SENTENCES, k=4)))
    b.text(" Order reference: INV-")
    b.text(str(rng.randint(1000, 9999)))
    b.text(". Ticket status: resolved.")
    return b


TEMPLATES = [support_ticket, billing_dispute, clinical_note, devops_incident_email, clean_negative]
CATEGORY_NAMES = [
    "support_ticket",
    "billing_dispute",
    "clinical_note",
    "devops_incident_email",
    "clean_negative",
]


def generate(n_per_template: int, seed: int = SEED) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows = []
    doc_id = 0
    for template, category in zip(TEMPLATES, CATEGORY_NAMES, strict=True):
        for i in range(n_per_template):
            builder = template(rng, doc_id)
            rows.append(
                {
                    "id": doc_id,
                    "category": category,
                    "synthetic": True,
                    "text": builder.build(),
                    "entities": builder.entities,
                }
            )
            doc_id += 1
    return rows


def main() -> None:
    n_per_template = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    for row in generate(n_per_template):
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
