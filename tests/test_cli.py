import json

from veil.cli import main


def test_mask_then_restore_round_trip(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    input_path = tmp_path / "in.txt"
    input_path.write_text("Contact alice@example.com about invoice 4471.\n")
    vault_path = tmp_path / "vault.json"
    masked_path = tmp_path / "masked.txt"

    rc = main(["mask", str(input_path), "--vault", str(vault_path)])
    assert rc == 0
    masked = capsys.readouterr().out
    assert "alice@example.com" not in masked
    masked_path.write_text(masked)
    assert vault_path.exists()

    rc = main(["restore", str(masked_path), "--vault", str(vault_path)])
    assert rc == 0
    restored = capsys.readouterr().out
    assert restored == "Contact alice@example.com about invoice 4471.\n"


def test_audit_reports_leak_and_exits_nonzero(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    input_path = tmp_path / "in.txt"
    input_path.write_text("Contact alice@example.com.\n")
    vault_path = tmp_path / "vault.json"
    main(["mask", str(input_path), "--vault", str(vault_path)])
    capsys.readouterr()

    leak_path = tmp_path / "leak.txt"
    leak_path.write_text("Whoops, alice@example.com leaked.\n")
    rc = main(["audit", str(leak_path), "--vault", str(vault_path), "--json"])
    out = capsys.readouterr().out
    assert rc == 1
    payload = json.loads(out)
    assert payload[0]["kind"] == "leaked_original"


def test_audit_clean_text_exits_zero(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    input_path = tmp_path / "in.txt"
    input_path.write_text("Contact alice@example.com.\n")
    vault_path = tmp_path / "vault.json"
    main(["mask", str(input_path), "--vault", str(vault_path)])
    capsys.readouterr()

    clean_path = tmp_path / "clean.txt"
    clean_path.write_text("Nothing sensitive here.\n")
    rc = main(["audit", str(clean_path), "--vault", str(vault_path)])
    assert rc == 0


def test_missing_input_file_reports_clean_error(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    rc = main(["mask", str(tmp_path / "nope.txt"), "--vault", str(tmp_path / "v.json")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err


def test_missing_vault_for_restore_reports_clean_error(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    input_path = tmp_path / "in.txt"
    input_path.write_text("hello\n")
    rc = main(["restore", str(input_path), "--vault", str(tmp_path / "nope.json")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err


def test_restore_exact_flag(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    input_path = tmp_path / "in.txt"
    input_path.write_text("Contact alice@example.com.\n")
    vault_path = tmp_path / "vault.json"
    main(["mask", str(input_path), "--vault", str(vault_path)])
    masked = capsys.readouterr().out
    masked_path = tmp_path / "masked.txt"
    masked_path.write_text(masked)

    rc = main(["restore", str(masked_path), "--vault", str(vault_path), "--exact"])
    assert rc == 0
    assert "alice@example.com" in capsys.readouterr().out
