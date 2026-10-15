"""Temporary AWS identifiers must not depend on an entropy heuristic."""

from __future__ import annotations

import pytest

from veil import Masker
from veil.detectors.secrets import SecretDetector


@pytest.mark.parametrize("prefix", ["AKIA", "ASIA"])
def test_recognized_aws_prefix_covers_keys_rejected_by_entropy_or_word_filters(prefix: str) -> None:
    for body in ["4J2RI3GSPL7SLMJN", "YSY3Y52XLD7NZ34H", "ZKCBPDZKGSLHIEPC", "QWERTYUIOPASDFGH"]:
        key = prefix + body
        found = SecretDetector().find(key)
        assert [(e.value, e.detector) for e in found] == [(key, "secret:aws_access_key")]


def test_temporary_key_reuses_one_surrogate_in_env_ini_and_json_without_editing_keys() -> None:
    key = "ASIAZKCBPDZKGSLHIEPC"
    source = f'AWS_ACCESS_KEY_ID={key}\naws_access_key_id = {key}\n{{"AccessKeyId":"{key}"}}'
    expected = (
        'AWS_ACCESS_KEY_ID=⟨SECRET_1⟩\naws_access_key_id = ⟨SECRET_1⟩\n{"AccessKeyId":"⟨SECRET_1⟩"}'
    )
    masker = Masker()
    assert masker.mask(source) == expected
    assert len(masker.vault) == 1 and masker.restore(expected) == source


def test_aws_prefix_recognition_keeps_whole_token_boundaries() -> None:
    key = "ASIAZKCBPDZKGSLHIEPC"
    for token in [key[:-1], key + "A", "A" + key, "_" + key, key + "_", key.lower()]:
        assert not any(e.detector == "secret:aws_access_key" for e in SecretDetector().find(token))
    # IAM role/user IDs and ordinary words are not newly recognized AWS keys.
    for token in ["AROAZKCBPDZKGSLHIEPC", "AIDAZKCBPDZKGSLHIEPC", "ASIA", "travel in ASIA"]:
        assert not any(e.detector == "secret:aws_access_key" for e in SecretDetector().find(token))


def test_temporary_key_candidate_does_not_fragment_a_mailbox_or_credential_url() -> None:
    key = "ASIAZKCBPDZKGSLHIEPC"
    for source, expected in [
        (f"{key}@example.org", "⟨EMAIL_1⟩"),
        (f"https://example.org/?token={key}", "⟨URL_CREDENTIAL_1⟩"),
    ]:
        masker = Masker()
        assert masker.mask(source) == expected
        assert masker.restore(expected) == source
