"""Built-in regex-and-validation detectors.

Each detector is stateless and independently testable; :mod:`veil.masker`
composes whichever subset it is given. ``DEFAULT_DETECTORS`` excludes
:class:`~veil.detectors.address.AddressDetector` because it is the
weakest/heuristic one (see its docstring) and shouldn't run unasked.
"""

from __future__ import annotations

from veil.detectors.address import AddressDetector
from veil.detectors.base import Detector
from veil.detectors.card import CardDetector
from veil.detectors.dob import DobDetector
from veil.detectors.email import EmailDetector
from veil.detectors.iban import IbanDetector
from veil.detectors.ip import IpDetector
from veil.detectors.phone import PhoneDetector
from veil.detectors.secrets import SecretDetector
from veil.detectors.ssn import SsnDetector
from veil.detectors.url import UrlCredentialDetector

__all__ = [
    "AddressDetector",
    "CardDetector",
    "Detector",
    "DobDetector",
    "EmailDetector",
    "IbanDetector",
    "IpDetector",
    "PhoneDetector",
    "SecretDetector",
    "SsnDetector",
    "UrlCredentialDetector",
    "default_detectors",
    "all_detectors",
]


def default_detectors() -> list[Detector]:
    """The detector set used unless a caller opts into address heuristics.

    Returns fresh instances each call; detectors are stateless, so this is
    only to keep callers from sharing mutable list state by accident.
    """
    return [
        EmailDetector(),
        PhoneDetector(),
        CardDetector(),
        IbanDetector(),
        SsnDetector(),
        IpDetector(),
        UrlCredentialDetector(),
        SecretDetector(),
        DobDetector(),
    ]


def all_detectors() -> list[Detector]:
    """``default_detectors()`` plus the opt-in address heuristic."""
    return [*default_detectors(), AddressDetector()]
