from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"


def _run_install(*args: str, home: Path, tmpdir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["TMPDIR"] = str(tmpdir)
    env["PIP_CACHE_DIR"] = str(tmpdir / "pip-cache")
    return subprocess.run(
        ["/bin/sh", str(INSTALL), *args],
        check=False,
        text=True,
        capture_output=True,
        env=env,
        cwd=ROOT,
    )


def test_installer_dry_run_writes_nothing(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    home = tmp_path / "home"
    temp = tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()

    result = _run_install(
        "--dry-run",
        "--prefix",
        str(prefix),
        "--no-onboard",
        home=home,
        tmpdir=temp,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "Would create venv:" in result.stdout
    assert "Would expose command:" in result.stdout
    assert "Dry run only: no files were written." in result.stdout
    assert "sudo: no" in result.stdout
    assert "shell profile edits: no" in result.stdout
    assert "daemon/background watcher: no" in result.stdout
    assert not prefix.exists()


def test_installer_ref_requires_git_source_and_writes_nothing(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    home = tmp_path / "home"
    temp = tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()

    result = _run_install(
        "--dry-run",
        "--prefix",
        str(prefix),
        "--source",
        str(ROOT),
        "--ref",
        "v0.1.0",
        home=home,
        tmpdir=temp,
    )

    assert result.returncode != 0
    assert "--ref is only supported with a Git URL" in result.stderr
    assert not prefix.exists()


def test_installer_help_documents_safe_flags() -> None:
    result = subprocess.run(
        ["/bin/sh", str(INSTALL), "--help"],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "--dry-run" in result.stdout
    assert "--prefix <path>" in result.stdout
    assert "--no-onboard" in result.stdout
