"""A header key is context, never synthetic source for a name backend."""

import pytest

from veil import Masker, Restorer, VaultError
from veil.backends import KnownEntitiesBackend
from veil.detectors.secrets import SecretDetector
from veil.integrations._json_arguments import mask_arguments, mask_string_value, restore_arguments


@pytest.mark.parametrize("key", ["Authorization", "authorization", "Proxy-Authorization"])
@pytest.mark.parametrize(
    "value,credential",
    [
        ("Bearer abc", "abc"),
        ("Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("\t'Bearer ab.c_d-ef~g+/=='", "ab.c_d-ef~g+/=="),
    ],
)
def test_only_original_value_enters_masking_and_vault(
    key: str, value: str, credential: str
) -> None:
    masker = Masker(name_backends=[KnownEntitiesBackend(orgs=["Authorization:"])])
    masked = mask_string_value(value, masker, key=key)
    assert masked == value.replace(credential, "⟨SECRET_1⟩")
    assert [mapping.original for mapping in masker.vault.mappings()] == [credential]
    assert masker.restore(masked) == masker.restore(masked, tolerant=False) == value
    restorer = Restorer(masker.vault)
    assert "".join(restorer.feed(char) for char in masked) + restorer.flush() == value
    # The public field-context API has the same behavior, with no synthetic label.
    assert masker.mask(value, field_name=key) == masked


def test_real_label_text_is_still_masked_as_source_and_json_spelling_is_preserved() -> None:
    masker = Masker(name_backends=[KnownEntitiesBackend(orgs=["Authorization:"])])
    source = '{ "Authorization":"Bearer abc", "note":"Authorization:", "n":1.2300e+40 }'
    masked = mask_arguments(source, masker)
    expected = source.replace("Bearer abc", "Bearer ⟨SECRET_1⟩").replace(
        '"note":"Authorization:"', '"note":"⟨ORG_1⟩"'
    )
    assert masked == expected
    assert restore_arguments(masked, masker) == source
    assert [mapping.original for mapping in masker.vault.mappings()] == ["abc", "Authorization:"]


def test_sensitive_header_key_keeps_the_existing_rejection_policy() -> None:
    masker = Masker(name_backends=[KnownEntitiesBackend(orgs=["Authorization"])])
    with pytest.raises(VaultError, match="sensitive JSON key"):
        mask_arguments('{"Authorization":"Bearer abc"}', masker)
    assert len(masker.vault) == 0


@pytest.mark.parametrize(
    "value", ["Bearer", "Bearer\nabc", "Bearer abc:def", "Bearer abc=def", "Basic $TOKEN"]
)
def test_field_context_does_not_accept_a_shorter_unsupported_credential(value: str) -> None:
    assert SecretDetector().find_in_field("Authorization", value) == []


def test_bearer_without_a_header_key_retains_the_existing_policy() -> None:
    assert Masker().mask("Bearer abc") == "Bearer abc"
