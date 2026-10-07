"""Private, atomic local writes shared by vault persistence and the CLI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: str, text: str) -> None:
    """Replace a file from a temporary sibling (0600 on POSIX).

    A failed write leaves the previous file intact. This does not coordinate
    concurrent writers or promise survival of a whole-machine power failure.
    """
    target = Path(path)
    if target.is_symlink():
        raise OSError("refusing to write through a symbolic link")
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
