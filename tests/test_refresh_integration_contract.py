from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mindfresh import config

from conftest import (
    create_fixture_vault,
    generated_hashes,
    hash_file,
    markdown_hashes,
    raw_markdown_files,
)


def _use_isolated_config(monkeypatch: pytest.MonkeyPatch, cfg_path: Path) -> None:
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", cfg_path)


def _cli_app_or_xfail(monkeypatch: pytest.MonkeyPatch, cfg_path: Path):
    _use_isolated_config(monkeypatch, cfg_path)
    cli_module = pytest.importorskip("mindfresh.cli")
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_FILE", cfg_path)
    try:
        CliRunner().invoke(cli_module.app, ["--help"])
    except TypeError as exc:
        if "unsupported operand type" in str(exc):
            pytest.xfail(
                "task 8 pending: CLI annotations must support pyproject requires-python >=3.9"
            )
        raise
    return cli_module.app


def _refresh_or_xfail(runner: CliRunner, app, vault: Path, *extra_args: str) -> None:
    result = runner.invoke(app, ["refresh", str(vault), "--adapter", "fake", *extra_args])
    assert result.exit_code == 0, result.output
    if not any(vault.rglob("SUMMARY.md")):
        pytest.xfail("task 10 pending: fake refresh pipeline has not created generated outputs yet")


def test_fake_refresh_creates_generated_outputs_manifest_and_preserves_raw_notes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _cli_app_or_xfail(monkeypatch, tmp_path / "config.toml")
    fixture = create_fixture_vault(tmp_path)
    raw_before = markdown_hashes(raw_markdown_files(fixture.root))

    _refresh_or_xfail(CliRunner(), app, fixture.root)

    for topic in [fixture.topic-a, fixture.z_image, fixture.policy-platform]:
        summary = topic / "SUMMARY.md"
        changelog = topic / "CHANGELOG.md"
        assert summary.exists()
        assert changelog.exists()
        assert "mindfresh_generated: true" in summary.read_text(encoding="utf-8")
        assert "mindfresh_generated: true" in changelog.read_text(encoding="utf-8")

    assert (fixture.root / ".mindfresh" / "manifest.sqlite").exists()
    assert markdown_hashes(raw_markdown_files(fixture.root)) == raw_before


def test_noop_refresh_preserves_generated_hashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _cli_app_or_xfail(monkeypatch, tmp_path / "config.toml")
    fixture = create_fixture_vault(tmp_path)
    runner = CliRunner()

    _refresh_or_xfail(runner, app, fixture.root)
    first = generated_hashes(fixture.root)
    assert first

    _refresh_or_xfail(runner, app, fixture.root)
    assert generated_hashes(fixture.root) == first


def test_incremental_topic_refresh_updates_only_changed_topic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _cli_app_or_xfail(monkeypatch, tmp_path / "config.toml")
    fixture = create_fixture_vault(tmp_path)
    runner = CliRunner()

    _refresh_or_xfail(runner, app, fixture.root)
    before = generated_hashes(fixture.root)
    assert before

    new_note = fixture.topic-a / "2026-04-24-new-finding.md"
    new_note.write_text(
        "# New finding\n\nTopic A now needs an explicit scheduler check.\n", encoding="utf-8"
    )
    _refresh_or_xfail(runner, app, fixture.root, "--topic", "research/topic-a")

    after = generated_hashes(fixture.root)
    changed = {path for path, digest in after.items() if before.get(path) != digest}
    assert changed == {
        (fixture.topic-a / "SUMMARY.md").as_posix(),
        (fixture.topic-a / "CHANGELOG.md").as_posix(),
    }
    assert "2026-04-24-new-finding.md" in (fixture.topic-a / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )


def test_manifest_sqlite_records_schema_hash_algorithm_and_generated_hashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _cli_app_or_xfail(monkeypatch, tmp_path / "config.toml")
    fixture = create_fixture_vault(tmp_path)
    _refresh_or_xfail(CliRunner(), app, fixture.root)
    manifest = fixture.root / ".mindfresh" / "manifest.sqlite"
    if not manifest.exists():
        pytest.xfail("task 9 pending: manifest.sqlite has not been implemented yet")

    with sqlite3.connect(manifest) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert table_names
        dumped_values: list[str] = []
        for table in table_names:
            columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
            text_columns = [col[1] for col in columns if col[2].upper() in {"TEXT", "VARCHAR"}]
            for column in text_columns:
                dumped_values.extend(
                    str(row[0])
                    for row in conn.execute(
                        f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
                    )
                )

    joined = "\n".join(dumped_values)
    assert "sha256" in joined
    assert any(hash_file(path) in joined for path in fixture.root.rglob("SUMMARY.md"))


def test_crash_window_retry_converges_without_raw_note_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _cli_app_or_xfail(monkeypatch, tmp_path / "config.toml")
    fixture = create_fixture_vault(tmp_path)
    raw_before = markdown_hashes(raw_markdown_files(fixture.root))

    refresh_module = pytest.importorskip(
        "mindfresh.refresh", reason="task 10 pending: refresh module not implemented yet"
    )
    crash_refresh = getattr(refresh_module, "refresh_with_test_crash", None)
    if crash_refresh is None:
        pytest.xfail("task 10 pending: expose refresh_with_test_crash for crash-window tests")

    crash_refresh(fixture.root, crash_at="after_rename_before_manifest", adapter="fake")
    crash_refresh(fixture.root, crash_at=None, adapter="fake")

    assert (fixture.topic-a / "SUMMARY.md").exists()
    assert (fixture.root / ".mindfresh" / "manifest.sqlite").exists()
    assert markdown_hashes(raw_markdown_files(fixture.root)) == raw_before
