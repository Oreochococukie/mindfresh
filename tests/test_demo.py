from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mindfresh import cli
from mindfresh.demo import create_demo_vault, run_demo
from mindfresh.scanner import hash_file


BANNED_SAMPLE_TERMS = ("amazon", "fba", "comfyui", "personal")


def test_run_demo_dry_run_reports_metadata_without_writing_generated_files(tmp_path: Path) -> None:
    report = run_demo(tmp_path / "demo-vault", dry_run=True)

    assert report.dry_run is True
    assert report.vault_root == (tmp_path / "demo-vault").resolve().as_posix()
    assert len(report.results) == 1
    result = report.results[0]
    assert result.topic == "knowledge/garden-planning"
    assert result.status == "would-refresh"
    assert result.run_id is not None
    assert result.summary_hash is not None
    assert result.changelog_hash is not None
    assert result.trigger_files == [
        "knowledge/garden-planning/2026-04-20-soil-notes.md",
        "knowledge/garden-planning/2026-04-22-watering-notes.md",
    ]
    assert len(report.sample_notes) == 2
    assert all(note.sha256_before == note.sha256_after for note in report.sample_notes)
    assert {artifact.kind for artifact in report.generated_artifacts} == {"summary", "changelog"}
    assert all(not artifact.exists for artifact in report.generated_artifacts)
    assert all(artifact.sha256 is None for artifact in report.generated_artifacts)
    assert not any(Path(report.vault_root).rglob("SUMMARY.md"))
    assert not any(Path(report.vault_root).rglob("CHANGELOG.md"))


def test_run_demo_real_mode_generates_artifacts_and_preserves_raw_notes(tmp_path: Path) -> None:
    report = run_demo(tmp_path / "demo-vault", dry_run=False)

    assert [result.status for result in report.results] == ["refreshed"]
    assert all(note.sha256_before == note.sha256_after for note in report.sample_notes)
    artifact_by_kind = {artifact.kind: artifact for artifact in report.generated_artifacts}
    assert set(artifact_by_kind) == {"summary", "changelog"}
    for artifact in artifact_by_kind.values():
        path = Path(report.vault_root) / artifact.path
        assert artifact.exists
        assert artifact.sha256 == hash_file(path)
        assert "mindfresh_generated: true" in path.read_text(encoding="utf-8")


def test_create_demo_vault_uses_neutral_sample_markdown(tmp_path: Path) -> None:
    sample_paths = create_demo_vault(tmp_path / "demo-vault")

    assert len(sample_paths) == 2
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in sample_paths)
    for banned_term in BANNED_SAMPLE_TERMS:
        assert banned_term not in combined


def test_cli_demo_dry_run_is_copy_paste_safe(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli.app,
        ["demo", "--dry-run", "--vault-root", str(tmp_path / "demo-vault")],
    )

    assert result.exit_code == 0, result.output
    assert "Mindfresh demo smoke test" in result.output
    assert "dry-run" in result.output
    assert "PASS raw note unchanged" in result.output
    assert not any((tmp_path / "demo-vault").rglob("SUMMARY.md"))
