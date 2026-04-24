from __future__ import annotations

from pathlib import Path
import hashlib
import os
import tempfile
from typing import Optional


def write_atomic_text(target: Path, content: str) -> tuple[str, str]:
    """Write content atomically and return (final_path, sha256 hex).

    The temp file is created in the target directory so os.replace is atomic
    on the same filesystem. fsync is best-effort for crash-safety.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=target.parent,
            delete=False,
            encoding="utf-8",
        ) as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
            tmp_path = Path(fp.name)

        os.replace(tmp_path, target)
        _fsync_directory(target.parent)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return str(target), digest


def _fsync_directory(directory: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
