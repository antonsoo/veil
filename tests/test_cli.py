import json
import os
import subprocess
import sys

import pytest

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


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    import veil

    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"veil {veil.__version__}"


# -- the command line as a shell uses it: pipes, redirection, another code page ----------


def _run(
    args: list[str], stdin: bytes | None = None, encoding: str | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run ``veil`` in a subprocess, with bytes in and out so encodings are what they are.

    ``encoding`` is the one Python would give the pipes: on Windows a redirected stdout or
    stdin gets the ANSI code page (cp1252 in the west), which PYTHONIOENCODING reproduces.
    """
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    if encoding:
        env["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [sys.executable, "-m", "veil.cli", *args], input=stdin, capture_output=True, env=env
    )


TICKET = "Straße 5, Köln: write to hans@example.de or call +1 (415) 555-0134.\n"


def test_stdin_is_read_when_no_file_is_named(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # The pipeline in the module's own docstring: `cat ticket.txt | veil mask --vault v.json`.
    vault = str(tmp_path / "v.json")
    masked = _run(["mask", "--vault", vault], stdin=TICKET.encode())
    assert masked.returncode == 0, masked.stderr.decode()
    assert masked.stdout.decode() == "Straße 5, Köln: write to ⟨EMAIL_1⟩ or call ⟨PHONE_1⟩.\n"
    restored = _run(["restore", "--vault", vault], stdin=masked.stdout)
    assert restored.stdout.decode() == TICKET
    audited = _run(["audit", "--vault", vault], stdin=masked.stdout)
    assert audited.returncode == 0
    assert audited.stdout.decode().strip() == "veil audit: no leaks found"


@pytest.mark.parametrize("encoding", ["cp1252", "ascii", "cp437"])
def test_pipes_are_utf8_whatever_the_code_page(tmp_path, encoding: str) -> None:  # type: ignore[no-untyped-def]
    # A legacy code page has no surrogate brackets: writing them to a redirected stdout
    # raised UnicodeEncodeError, and UTF-8 on stdin was read as mojibake.
    source = tmp_path / "ticket.txt"
    source.write_text(TICKET, encoding="utf-8")
    vault = str(tmp_path / "v.json")
    from_file = _run(["mask", str(source), "--vault", vault], encoding=encoding)
    assert from_file.returncode == 0, from_file.stderr.decode()
    expected = "Straße 5, Köln: write to ⟨EMAIL_1⟩ or call ⟨PHONE_1⟩.\n"
    assert from_file.stdout.decode("utf-8") == expected
    from_stdin = _run(["mask", "--vault", vault], stdin=TICKET.encode(), encoding=encoding)
    assert from_stdin.stdout.decode("utf-8") == expected
    restored = _run(["restore", "--vault", vault], stdin=from_stdin.stdout, encoding=encoding)
    assert restored.stdout.decode("utf-8") == TICKET
    # audit prints the leaked value, which is not ASCII either
    leak = _run(
        ["audit", "--vault", vault],
        stdin="hans@example.de wohnt in Köln\n".encode(),
        encoding=encoding,
    )
    assert leak.returncode == 1
    assert "'hans@example.de'" in leak.stdout.decode("utf-8")


def test_stdin_that_is_not_utf8_is_refused_in_one_line(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = _run(["mask", "--vault", str(tmp_path / "v.json")], stdin=TICKET.encode("latin-1"))
    assert result.returncode == 2
    assert result.stdout == b""
    message = result.stderr.decode()
    assert message.startswith("veil mask: could not decode input as UTF-8")
    assert len(message.strip().splitlines()) == 1


def test_line_endings_pass_through(tmp_path) -> None:  # type: ignore[no-untyped-def]
    vault = str(tmp_path / "v.json")
    crlf = b"To: hans@example.de\r\nCc: erika@example.de\r\n\r\nCall +1 (415) 555-0134"
    masked = _run(["mask", "--vault", vault], stdin=crlf)
    assert masked.stdout == "To: ⟨EMAIL_1⟩\r\nCc: ⟨EMAIL_2⟩\r\n\r\nCall ⟨PHONE_1⟩\r\n".encode()
    # The same text with LF endings masks to the same surrogates, with LF endings.
    lf = _run(["mask", "--vault", str(tmp_path / "v2.json")], stdin=crlf.replace(b"\r\n", b"\n"))
    assert lf.stdout == masked.stdout.replace(b"\r\n", b"\n")
    source = tmp_path / "crlf.txt"
    source.write_bytes(crlf)
    out = tmp_path / "masked.txt"
    to_file = _run(["mask", str(source), "--vault", vault, "-o", str(out)])
    assert to_file.returncode == 0 and to_file.stdout == b""
    assert out.read_bytes() == masked.stdout
    back = tmp_path / "restored.txt"
    _run(["restore", str(out), "--vault", vault, "--output", str(back)])
    assert back.read_bytes() == crlf + b"\r\n"
