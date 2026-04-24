from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FixtureVault:
    root: Path
    topic-a: Path
    z_image: Path
    policy-platform: Path


def create_fixture_vault(tmp_path: Path) -> FixtureVault:
    """Create the PRD/test-spec fixture vault with raw notes only."""
    root = tmp_path / "vault"
    topic-a = root / "research" / "topic-a"
    z_image = root / "research" / "topic-b"
    policy-platform = root / "policy" / "policy-platform"

    topic-a.mkdir(parents=True)
    z_image.mkdir(parents=True)
    policy-platform.mkdir(parents=True)

    (topic-a / "2026-04-01-baseline.md").write_text(
        "# Topic A baseline\n\nTopic A workflow uses the baseline node set.\n", encoding="utf-8"
    )
    (topic-a / "2026-04-20-comparison.md").write_text(
        "# Topic A comparison\n\nA newer note changes recommended sampler settings.\n",
        encoding="utf-8",
    )
    (z_image / "2026-04-10-baseline.md").write_text(
        "# Topic B baseline\n\nTopic B keeps a separate topic state.\n", encoding="utf-8"
    )
    (policy-platform / "2026-04-01-policy.md").write_text(
        "# policy platform policy\n\nPolicy policy evidence belongs to its own topic.\n",
        encoding="utf-8",
    )
    return FixtureVault(root=root, topic-a=topic-a, z_image=z_image, policy-platform=policy-platform)


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
