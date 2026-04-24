from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional

GENERATED_FILE_NAMES = {"SUMMARY.md", "CHANGELOG.md"}
INTERNAL_DIR_NAMES = {".mindfresh"}
GENERATED_DIR_NAMES = {"_generated", "_review"}
EXCLUDED_DIR_NAMES = INTERNAL_DIR_NAMES | GENERATED_DIR_NAMES
HASH_ALGORITHM = "sha256"


@dataclass(frozen=True)
class Topic:
    vault_root: Path
    relative_path: Path

    @property
    def path(self) -> Path:
        return self.vault_root / self.relative_path


@dataclass(frozen=True)
class SourceSnapshot:
    vault_root: Path
    relative_path: Path
    sha256: str
    size: int
    mtime_ns: int

    @property
    def path(self) -> Path:
        return self.vault_root / self.relative_path


def _is_excluded_dir_name(name: str) -> bool:
    return name in EXCLUDED_DIR_NAMES or name.startswith(".")


def _has_excluded_part(relative_path: Path) -> bool:
    return any(_is_excluded_dir_name(part) for part in relative_path.parts)


def _relative_to_vault(path: Path, vault_root: Optional[Path]) -> Path:
    if vault_root is None:
        return Path(path)
    return Path(path).resolve().relative_to(Path(vault_root).expanduser().resolve())


def _frontmatter_block(path: Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:index]
    return []


def _frontmatter_bool(path: Path, key: str) -> bool:
    for line in _frontmatter_block(path):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        raw_key, raw_value = stripped.split(":", 1)
        if raw_key.strip() != key:
            continue
        value = raw_value.split("#", 1)[0].strip().strip('"\'').lower()
        return value in {"true", "yes", "on", "1"}
    return False


def is_generated_file(path: Path) -> bool:
    """Return true for generated Markdown artifacts that must never be source input."""
    path = Path(path)
    if path.name in GENERATED_FILE_NAMES:
        return True
    return path.suffix.lower() == ".md" and _frontmatter_bool(path, "mindfresh_generated")


def is_source_markdown(path: Path, *, vault_root: Optional[Path] = None) -> bool:
    """Return true only for raw source Markdown inside an allowed source boundary."""
    path = Path(path)
    if path.suffix.lower() != ".md" or not path.is_file():
        return False

    try:
        relative_path = _relative_to_vault(path, vault_root)
    except ValueError:
        return False

    if _has_excluded_part(relative_path):
        return False
    if is_generated_file(path):
        return False
    return True


def iter_source_markdown(vault_root: Path) -> Iterator[Path]:
    """Yield raw source Markdown files under a vault while pruning excluded trees."""
    root = Path(vault_root).expanduser().resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dir_path = Path(dirpath)
        rel_dir = dir_path.relative_to(root)
        if rel_dir != Path(".") and _has_excluded_part(rel_dir):
            dirnames[:] = []
            continue

        dirnames[:] = sorted(name for name in dirnames if not _is_excluded_dir_name(name))
        for filename in sorted(filenames):
            candidate = dir_path / filename
            if is_source_markdown(candidate, vault_root=root):
                yield candidate


def detect_topics(vault_root: Path) -> List[Topic]:
    """Return topic directories that contain at least one direct raw source Markdown file."""
    root = Path(vault_root).expanduser().resolve()
    topic_paths = {source.parent.relative_to(root) for source in iter_source_markdown(root)}
    return [Topic(vault_root=root, relative_path=rel) for rel in sorted(topic_paths, key=_path_sort_key)]


def collect_topic_sources(topic: Topic) -> List[Path]:
    """Return direct raw source Markdown files for one topic, never generated artifacts."""
    base = topic.path
    if not base.is_dir():
        return []
    return [
        candidate
        for candidate in sorted(base.iterdir(), key=lambda item: item.name)
        if is_source_markdown(candidate, vault_root=topic.vault_root)
    ]


def hash_file(path: Path) -> str:
    """Compute the SHA-256 hash for a source or generated artifact."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_source(path: Path, *, vault_root: Path) -> SourceSnapshot:
    """Capture immutable source metadata used by manifest invalidation checks."""
    root = Path(vault_root).expanduser().resolve()
    source = Path(path).resolve()
    relative_path = source.relative_to(root)
    stat = source.stat()
    return SourceSnapshot(
        vault_root=root,
        relative_path=relative_path,
        sha256=hash_file(source),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def collect_topic_source_snapshots(topic: Topic) -> List[SourceSnapshot]:
    return [snapshot_source(source, vault_root=topic.vault_root) for source in collect_topic_sources(topic)]


def capture_source_hashes(paths: Iterable[Path], *, vault_root: Optional[Path] = None) -> Dict[str, str]:
    """Capture source hashes keyed by stable POSIX paths for raw-immutability checks."""
    root = Path(vault_root).expanduser().resolve() if vault_root is not None else None
    hashes: Dict[str, str] = {}
    for path in paths:
        candidate = Path(path).resolve()
        key = candidate.relative_to(root).as_posix() if root is not None else candidate.as_posix()
        hashes[key] = hash_file(candidate)
    return hashes


def assert_source_hashes_unchanged(before: Mapping[str, str], *, vault_root: Optional[Path] = None) -> None:
    """Raise if any previously captured source hash has changed or disappeared."""
    root = Path(vault_root).expanduser().resolve() if vault_root is not None else None
    changed: List[str] = []
    missing: List[str] = []
    for key, expected_hash in before.items():
        path = (root / key) if root is not None else Path(key)
        if not path.exists():
            missing.append(key)
            continue
        current_hash = hash_file(path)
        if current_hash != expected_hash:
            changed.append(key)

    if changed or missing:
        details = []
        if changed:
            details.append(f"changed={','.join(sorted(changed))}")
        if missing:
            details.append(f"missing={','.join(sorted(missing))}")
        raise RuntimeError("raw source files were modified: " + "; ".join(details))


def _path_sort_key(path: Path) -> str:
    value = path.as_posix()
    return "" if value == "." else value
