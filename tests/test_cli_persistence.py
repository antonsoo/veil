"""A CLI failure must not destroy source data or the only recovery mapping."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from veil.cli import main
from veil.vault import Vault


@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink"])
@pytest.mark.parametrize("command", ["mask", "restore"])
def test_output_cannot_replace_its_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], alias: str, command: str
) -> None:
    vault = tmp_path / "vault.json"
    Vault().save(str(vault))
    before = vault.read_bytes()
    output = tmp_path / "output.txt"
    if alias == "same":
        output = vault
    elif alias == "symlink":
        output.symlink_to(vault)
    else:
        os.link(vault, output)
    source = tmp_path / "source.txt"
    source.write_text("alice@example.com")
    assert main([command, str(source), "--vault", str(vault), "-o", str(output)]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "distinct files" in captured.err
    assert vault.read_bytes() == before
    assert source.read_text() == "alice@example.com"


def test_mask_does_not_emit_before_its_vault_is_saved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("alice@example.com")

    def fail_save(self: Vault, path: str) -> None:
        raise PermissionError("simulated inaccessible vault")

    monkeypatch.setattr(Vault, "save", fail_save)
    assert main(["mask", str(source), "--vault", str(tmp_path / "vault.json")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "simulated inaccessible vault" in captured.err
    assert "alice@example.com" not in captured.err


def test_failed_output_leaves_a_recoverable_saved_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("alice@example.com")
    vault = tmp_path / "vault.json"
    assert (
        main(["mask", str(source), "--vault", str(vault), "-o", str(tmp_path / "missing" / "out")])
        == 2
    )
    assert not capsys.readouterr().out
    assert Vault.load(str(vault)).originals() == ["alice@example.com"]


def test_output_cannot_overwrite_a_names_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Hello Alice")
    names = tmp_path / "names.txt"
    names.write_text("Alice\n")
    assert (
        main(
            [
                "mask",
                str(source),
                "--vault",
                str(tmp_path / "vault.json"),
                "--names-file",
                str(names),
                "-o",
                str(names),
            ]
        )
        == 2
    )
    assert "distinct files" in capsys.readouterr().err
    assert names.read_text() == "Alice\n"
