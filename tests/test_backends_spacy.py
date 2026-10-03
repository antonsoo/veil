"""Exercise the optional backend with a real, deterministic spaCy pipeline.

No language model download or NER accuracy claim: the entity ruler supplies
synthetic entities so this checks installation, loading, offsets, and masking.
"""

from pathlib import Path

import pytest

from veil import Masker
from veil.backends.spacy_backend import SpacyBackend

spacy = pytest.importorskip("spacy", reason="install the spacy extra to test the real backend")


@pytest.fixture
def backend(tmp_path: Path) -> SpacyBackend:
    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(
        [
            {"label": "PERSON", "pattern": "Alice"},
            {"label": "PER", "pattern": "Bob"},
            {"label": "ORG", "pattern": "Acme"},
            {"label": "GPE", "pattern": "Paris"},
            {"label": "LOC", "pattern": "Pacific"},
            {"label": "FAC", "pattern": "Central Station"},
            {"label": "DATE", "pattern": "Monday"},
        ]
    )
    model_path = tmp_path / "synthetic-model"
    nlp.to_disk(model_path)
    return SpacyBackend(model=str(model_path))


def test_entity_types_and_unicode_offsets(backend: SpacyBackend) -> None:
    text = "😀 Alice and Bob work at Acme in Paris near Pacific and Central Station on Monday."
    entities = backend.find(text)
    assert [(entity.value, entity.type.value) for entity in entities] == [
        ("Alice", "PERSON"),
        ("Bob", "PERSON"),
        ("Acme", "ORG"),
        ("Paris", "LOCATION"),
        ("Pacific", "LOCATION"),
        ("Central Station", "LOCATION"),
    ]
    for entity in entities:
        assert text[entity.span.start : entity.span.end] == entity.value
        assert entity.detector == "spacy"


def test_mask_restore_roundtrip_with_real_spacy(backend: SpacyBackend) -> None:
    masker = Masker(detectors=[], name_backends=[backend])
    text = "😀 Alice works at Acme in Paris. Alice returns on Monday."
    masked = masker.mask(text)
    assert masked == "😀 ⟨PERSON_1⟩ works at ⟨ORG_1⟩ in ⟨LOCATION_1⟩. ⟨PERSON_1⟩ returns on Monday."
    assert masker.restore(masked) == text
    assert backend.find("") == []


def test_missing_model_has_an_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="is not installed"):
        SpacyBackend(model=str(tmp_path / "missing-model"))
