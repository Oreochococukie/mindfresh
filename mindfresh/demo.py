from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import tempfile
from typing import Optional, Sequence

from .refresh import RefreshResult, refresh_vault
from .scanner import assert_source_hashes_unchanged, capture_source_hashes, hash_file


@dataclass(frozen=True)
class DemoSampleNote:
    """Raw sample note metadata captured before and after a demo refresh."""

    path: str
    sha256_before: str
    sha256_after: str


@dataclass(frozen=True)
class DemoGeneratedArtifact:
    """Generated artifact metadata for real demo runs.

    In dry-run mode the refresh pipeline returns would-be artifact hashes without
    writing files, so ``exists`` is false and ``sha256`` is ``None``.
    """

    topic: str
    kind: str
    path: str
    exists: bool
    sha256: Optional[str]


@dataclass(frozen=True)
class DemoReport:
    """Serializable smoke/demo result for future CLI integration."""

    vault_root: str
    dry_run: bool
    results: Sequence[RefreshResult]
    sample_notes: Sequence[DemoSampleNote]
    generated_artifacts: Sequence[DemoGeneratedArtifact]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _SampleNoteSpec:
    relative_path: str
    text: str


_SAMPLE_NOTES: Sequence[_SampleNoteSpec] = (
    _SampleNoteSpec(
        relative_path="knowledge/garden-planning/2026-04-20-soil-notes.md",
        text=(
            "# Soil preparation notes\n\n"
            "Raised beds need loose soil, compost, and a clear watering schedule.\n"
            "The latest observation is that seedlings recover best after gradual hardening.\n"
        ),
    ),
    _SampleNoteSpec(
        relative_path="knowledge/garden-planning/2026-04-22-watering-notes.md",
        text=(
            "# Watering notes\n\n"
            "Morning watering keeps leaves dry by evening and reduces avoidable stress.\n"
            "Duplicate reminder: use a clear watering schedule for the first two weeks.\n"
        ),
    ),
)


def create_demo_vault(vault_root: Path) -> list[Path]:
    """Create a neutral Markdown demo vault and return the raw sample note paths."""
    root = Path(vault_root).expanduser().resolve()
    sample_paths: list[Path] = []
    for spec in _SAMPLE_NOTES:
        path = root / spec.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(spec.text, encoding="utf-8")
        sample_paths.append(path)
    return sample_paths


def run_demo(
    vault_root: Optional[Path] = None,
    *,
    dry_run: bool = True,
    force: bool = False,
) -> DemoReport:
    """Run a safe fake-adapter smoke refresh against a temporary demo vault.

    If ``vault_root`` is omitted, a new directory under the system temp location
    is created so callers can inspect real-mode generated files after the helper
    returns. The helper always verifies the raw sample notes are byte-for-byte
    unchanged by ``refresh_vault``.
    """
    root = _default_demo_root() if vault_root is None else Path(vault_root).expanduser().resolve()
    sample_paths = create_demo_vault(root)
    before_hashes = capture_source_hashes(sample_paths, vault_root=root)

    results = refresh_vault(root, adapter_name="fake", dry_run=dry_run, force=force)

    assert_source_hashes_unchanged(before_hashes, vault_root=root)
    sample_notes = _sample_note_metadata(sample_paths, before_hashes, root)
    generated_artifacts = _generated_artifact_metadata(root, results)
    return DemoReport(
        vault_root=root.as_posix(),
        dry_run=dry_run,
        results=results,
        sample_notes=sample_notes,
        generated_artifacts=generated_artifacts,
    )


def _default_demo_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="mindfresh-demo-")) / "vault"


def _sample_note_metadata(
    sample_paths: Sequence[Path], before_hashes: dict[str, str], vault_root: Path
) -> list[DemoSampleNote]:
    notes: list[DemoSampleNote] = []
    for path in sample_paths:
        relative_path = path.relative_to(vault_root).as_posix()
        notes.append(
            DemoSampleNote(
                path=relative_path,
                sha256_before=before_hashes[relative_path],
                sha256_after=hash_file(path),
            )
        )
    return notes


def _generated_artifact_metadata(
    vault_root: Path, results: Sequence[RefreshResult]
) -> list[DemoGeneratedArtifact]:
    artifacts: list[DemoGeneratedArtifact] = []
    for result in results:
        topic_dir = vault_root / result.topic
        for kind, filename in (("summary", "SUMMARY.md"), ("changelog", "CHANGELOG.md")):
            path = topic_dir / filename
            artifacts.append(
                DemoGeneratedArtifact(
                    topic=result.topic,
                    kind=kind,
                    path=path.relative_to(vault_root).as_posix(),
                    exists=path.exists(),
                    sha256=hash_file(path) if path.exists() else None,
                )
            )
    return artifacts


__all__ = [
    "DemoGeneratedArtifact",
    "DemoReport",
    "DemoSampleNote",
    "create_demo_vault",
    "run_demo",
]
