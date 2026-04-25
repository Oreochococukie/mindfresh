from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FixtureVault:
    root: Path
    topic_a: Path
    topic_b: Path
    compliance: Path


def create_fixture_vault(tmp_path: Path) -> FixtureVault:
    """Create the PRD/test-spec fixture vault with raw notes only."""
    root = tmp_path / "vault"
    topic_a = root / "research" / "topic_a"
    topic_b = root / "research" / "topic-b"
    compliance = root / "policy" / "compliance"

    topic_a.mkdir(parents=True)
    topic_b.mkdir(parents=True)
    compliance.mkdir(parents=True)

    (topic_a / "2026-04-01-baseline.md").write_text(
        "# Topic A baseline\n\nTopic A workflow uses the baseline node set.\n", encoding="utf-8"
    )
    (topic_a / "2026-04-20-comparison.md").write_text(
        "# Topic A comparison\n\nA newer note changes recommended sampler settings.\n",
        encoding="utf-8",
    )
    (topic_b / "2026-04-10-baseline.md").write_text(
        "# Topic B baseline\n\nTopic B keeps a separate topic state.\n", encoding="utf-8"
    )
    (compliance / "2026-04-01-policy.md").write_text(
        "# Compliance policy\n\nPolicy policy evidence belongs to its own topic.\n",
        encoding="utf-8",
    )
    return FixtureVault(root=root, topic_a=topic_a, topic_b=topic_b, compliance=compliance)


def hash_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def markdown_hashes(paths: Iterable[Path]) -> dict[str, str]:
    return {path.as_posix(): hash_file(path) for path in sorted(paths)}


def raw_markdown_files(vault_root: Path) -> list[Path]:
    ignored = {"SUMMARY.md", "CHANGELOG.md"}
    return [
        path
        for path in vault_root.rglob("*.md")
        if path.name not in ignored and ".mindfresh" not in path.parts
    ]


def generated_hashes(vault_root: Path) -> dict[str, str]:
    return markdown_hashes(
        path
        for path in vault_root.rglob("*.md")
        if path.name in {"SUMMARY.md", "CHANGELOG.md"}
    )
