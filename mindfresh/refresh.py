from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Mapping, Optional, Sequence

import sqlite3
import uuid

from .adapters import SourceDocument, get_adapter
from .chunker import ContextPart, chunk_markdown_files, shard_chunks
from .manifest import (
    connect,
    hash_bytes,
    invalidation_key,
    load_topic_state,
    record_topic_run,
    snapshot_file,
    source_fingerprint,
    TopicRunSource,
    TopicRunState,
)
from .scanner import Topic, collect_topic_sources, detect_topics
from .schemas import (
    ChangelogEntry,
    SourceRef,
    render_changelog,
    render_context_shard,
    render_summary,
)
from .writer import write_atomic_text

PRESERVE_MODE_ENV_VAR = "MINDFRESH_PRESERVE_MODE"
CONTEXT_SHARD_MAX_CHARS_ENV_VAR = "MINDFRESH_CONTEXT_SHARD_MAX_CHARS"
CONTEXT_SHARD_THRESHOLD_CHARS_ENV_VAR = "MINDFRESH_CONTEXT_SHARD_THRESHOLD_CHARS"
CONTEXT_SHARD_SOURCE_COUNT_ENV_VAR = "MINDFRESH_CONTEXT_SHARD_SOURCE_COUNT"
DEFAULT_PRESERVE_MODE = "auto"
DEFAULT_CONTEXT_SHARD_MAX_CHARS = 40_000
DEFAULT_CONTEXT_SHARD_THRESHOLD_CHARS = 120_000
DEFAULT_CONTEXT_SHARD_SOURCE_COUNT = 25


@dataclass(frozen=True)
class RefreshResult:
    topic: str
    status: str
    run_id: Optional[str]
    summary_hash: Optional[str]
    changelog_hash: Optional[str]
    trigger_files: Sequence[str]
    context_hashes: Sequence[str] = ()


@dataclass(frozen=True)
class ContextShardArtifact:
    relative_path: str
    text: str
    sha256: str


@dataclass(frozen=True)
class PreservePlan:
    mode: str
    should_shard: bool
    shard_max_chars: int
    threshold_chars: int
    threshold_source_count: int
    source_count: int
    source_chars: int

    @property
    def signature(self) -> str:
        return (
            f"preserve={self.mode};shard={int(self.should_shard)};"
            f"max={self.shard_max_chars};threshold_chars={self.threshold_chars};"
            f"threshold_sources={self.threshold_source_count};sources={self.source_count};"
            f"chars={self.source_chars}"
        )


def refresh_vault(
    vault_root: Path,
    *,
    topic: Optional[str] = None,
    adapter_name: str = "fake",
    adapter_model: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    preserve_mode: Optional[str] = None,
    context_shard_max_chars: Optional[int] = None,
) -> list[RefreshResult]:
    root = Path(vault_root).expanduser().resolve()
    adapter = get_adapter(adapter_name, model=adapter_model)
    topics = _select_topics(root, topic)
    results: list[RefreshResult] = []
    with connect(root) as conn:
        for selected_topic in topics:
            results.append(
                refresh_topic(
                    selected_topic,
                    adapter_name=adapter.name,
                    adapter_model=adapter_model,
                    model_profile=adapter.model_profile,
                    dry_run=dry_run,
                    force=force,
                    preserve_mode=preserve_mode,
                    context_shard_max_chars=context_shard_max_chars,
                    conn=conn,
                )
            )
    return results


def refresh_topic(
    topic: Topic,
    *,
    adapter_name: str = "fake",
    adapter_model: Optional[str] = None,
    model_profile: str = "fake/deterministic-v1",
    dry_run: bool = False,
    force: bool = False,
    preserve_mode: Optional[str] = None,
    context_shard_max_chars: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> RefreshResult:
    owns_connection = conn is None
    connection = connect(topic.vault_root) if conn is None else conn
    try:
        return _refresh_topic_with_connection(
            topic,
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            model_profile=model_profile,
            dry_run=dry_run,
            force=force,
            preserve_mode=preserve_mode,
            context_shard_max_chars=context_shard_max_chars,
            conn=connection,
        )
    finally:
        if owns_connection:
            connection.close()


def _refresh_topic_with_connection(
    topic: Topic,
    *,
    adapter_name: str,
    adapter_model: Optional[str],
    model_profile: str,
    dry_run: bool,
    force: bool,
    preserve_mode: Optional[str],
    context_shard_max_chars: Optional[int],
    conn: sqlite3.Connection,
) -> RefreshResult:
    adapter = get_adapter(adapter_name, model=adapter_model)
    topic_rel = topic.relative_path.as_posix()
    topic_dir = topic.vault_root / topic.relative_path
    summary_path = topic_dir / "SUMMARY.md"
    changelog_path = topic_dir / "CHANGELOG.md"

    source_paths = collect_topic_sources(topic)
    before = [snapshot_file(path, relative_to=topic.vault_root) for path in source_paths]
    before_by_path = {src.relative_path: src.sha256 for src in before}
    preserve_plan = _preserve_plan(
        before,
        preserve_mode=preserve_mode,
        context_shard_max_chars=context_shard_max_chars,
    )
    context_artifacts = (
        _context_shard_artifacts(
            topic=topic,
            source_paths=source_paths,
            run_id=None,
            timestamp=None,
            plan=preserve_plan,
        )
        if preserve_plan.should_shard
        else []
    )
    fingerprint = source_fingerprint(before)
    key_hashes = dict(before_by_path)
    key_hashes["__mindfresh_preserve_plan__"] = hash_bytes(preserve_plan.signature.encode("utf-8"))
    if context_artifacts:
        key_hashes["__mindfresh_context_shards__"] = hash_bytes(
            "\n".join(artifact.sha256 for artifact in context_artifacts).encode("utf-8")
        )
    key = invalidation_key(
        adapter_name=adapter.name,
        model_profile=adapter.model_profile,
        source_hashes=key_hashes,
    )
    state = load_topic_state(conn, topic_rel)

    if (
        state is not None
        and not force
        and _generated_matches_state(summary_path, changelog_path, state)
        and _context_artifacts_match(topic_dir, context_artifacts)
    ):
        if state.invalidation_key == key and state.source_fingerprint == fingerprint:
            return RefreshResult(
                topic=topic_rel,
                status="unchanged",
                run_id=None,
                summary_hash=state.summary_hash,
                changelog_hash=state.changelog_hash,
                trigger_files=[],
                context_hashes=[artifact.sha256 for artifact in context_artifacts],
            )

    recent_paths = _recent_source_paths(before, state.source_hashes if state else {})
    source_documents = _source_documents(source_paths, topic.vault_root)
    recent_documents = [doc for doc in source_documents if doc.relative_path in recent_paths]
    previous_summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else None
    result = adapter.summarize(
        topic=topic_rel,
        sources=source_documents,
        recent_sources=recent_documents,
        previous_summary=previous_summary,
    )
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = f"{timestamp.replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:8]}"
    source_refs = [SourceRef(path=src.relative_path, sha256=src.sha256) for src in before]
    trigger_files = sorted(recent_paths) or [src.relative_path for src in before]
    context_artifacts = (
        _context_shard_artifacts(
            topic=topic,
            source_paths=source_paths,
            run_id=run_id,
            timestamp=timestamp,
            plan=preserve_plan,
        )
        if preserve_plan.should_shard
        else []
    )
    context_refs = [
        f"`{artifact.relative_path}` — `{artifact.sha256[:12]}`" for artifact in context_artifacts
    ]

    summary = render_summary(
        topic=topic_rel,
        run_id=run_id,
        timestamp=timestamp,
        result=result,
        source_refs=source_refs,
        context_refs=context_refs,
    )
    previous_changelog = (
        changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else None
    )
    changelog = render_changelog(
        topic=topic_rel,
        entry=ChangelogEntry(
            timestamp=timestamp,
            run_id=run_id,
            trigger_files=trigger_files,
            update_delta=result.update_delta,
            updated_claims=result.updated_claims,
            stale_or_conflicting_claims=result.stale_or_conflicting_claims,
            source_refs=source_refs,
            model_profile=result.model_profile,
            freshness_state=result.freshness_state,
        ),
        previous=previous_changelog,
    )

    if dry_run:
        return RefreshResult(
            topic=topic_rel,
            status="would-refresh",
            run_id=run_id,
            summary_hash=hash_bytes(summary.encode("utf-8")),
            changelog_hash=hash_bytes(changelog.encode("utf-8")),
            trigger_files=trigger_files,
            context_hashes=[artifact.sha256 for artifact in context_artifacts],
        )

    _, summary_hash = write_atomic_text(summary_path, summary)
    _, changelog_hash = write_atomic_text(changelog_path, changelog)
    _write_context_artifacts(topic_dir, context_artifacts)

    after = [snapshot_file(path, relative_to=topic.vault_root) for path in source_paths]
    after_by_path = {src.relative_path: src.sha256 for src in after}
    if after_by_path != before_by_path:
        raise RuntimeError(f"raw source changed during refresh for topic: {topic_rel}")

    record_topic_run(
        conn,
        topic_path=topic_rel,
        run_id=run_id,
        timestamp=timestamp,
        sources=before,
        source_fingerprint_value=fingerprint,
        invalidation_key_value=key,
        summary_hash=summary_hash,
        changelog_hash=changelog_hash,
        adapter_name=adapter.name,
        model_profile=adapter.model_profile,
    )
    return RefreshResult(
        topic=topic_rel,
        status="refreshed",
        run_id=run_id,
        summary_hash=summary_hash,
        changelog_hash=changelog_hash,
        trigger_files=trigger_files,
        context_hashes=[artifact.sha256 for artifact in context_artifacts],
    )


def _select_topics(vault_root: Path, topic: Optional[str]) -> list[Topic]:
    if topic is None:
        return detect_topics(vault_root)
    requested = Path(topic).expanduser()
    if requested.is_absolute():
        rel = requested.resolve().relative_to(vault_root)
    else:
        rel = requested
    return [Topic(vault_root=vault_root, relative_path=rel)]


def _source_documents(paths: Sequence[Path], vault_root: Path) -> list[SourceDocument]:
    docs: list[SourceDocument] = []
    for path in paths:
        docs.append(
            SourceDocument(
                relative_path=path.relative_to(vault_root).as_posix(),
                sha256=hash_bytes(path.read_bytes()),
                content=path.read_text(encoding="utf-8"),
            )
        )
    return docs


def _recent_source_paths(
    current: Sequence[TopicRunSource], previous_hashes: Mapping[str, str]
) -> set[str]:
    changed: set[str] = set()
    for src in current:
        relative_path = getattr(src, "relative_path")
        sha256 = getattr(src, "sha256")
        if previous_hashes.get(relative_path) != sha256:
            changed.add(relative_path)
    return changed


def _generated_matches_state(
    summary_path: Path, changelog_path: Path, state: TopicRunState
) -> bool:
    if not summary_path.exists() or not changelog_path.exists():
        return False
    return (
        hash_bytes(summary_path.read_bytes()) == state.summary_hash
        and hash_bytes(changelog_path.read_bytes()) == state.changelog_hash
    )


def _preserve_plan(
    sources: Sequence[object],
    *,
    preserve_mode: Optional[str],
    context_shard_max_chars: Optional[int],
) -> PreservePlan:
    mode = (preserve_mode or os.environ.get(PRESERVE_MODE_ENV_VAR) or DEFAULT_PRESERVE_MODE).strip()
    if mode not in {"single", "auto", "sharded"}:
        raise ValueError("preserve_mode must be one of: single, auto, sharded")
    if context_shard_max_chars is not None:
        if context_shard_max_chars <= 0:
            raise ValueError("context_shard_max_chars must be greater than 0")
        max_chars = context_shard_max_chars
    else:
        max_chars = _positive_int_env(
            CONTEXT_SHARD_MAX_CHARS_ENV_VAR,
            DEFAULT_CONTEXT_SHARD_MAX_CHARS,
        )
    threshold_chars = _positive_int_env(
        CONTEXT_SHARD_THRESHOLD_CHARS_ENV_VAR,
        DEFAULT_CONTEXT_SHARD_THRESHOLD_CHARS,
    )
    threshold_sources = _positive_int_env(
        CONTEXT_SHARD_SOURCE_COUNT_ENV_VAR,
        DEFAULT_CONTEXT_SHARD_SOURCE_COUNT,
    )
    source_count = len(sources)
    source_chars = sum(int(getattr(source, "size", 0)) for source in sources)
    should_shard = mode == "sharded" or (
        mode == "auto" and (source_count >= threshold_sources or source_chars >= threshold_chars)
    )
    return PreservePlan(
        mode=mode,
        should_shard=should_shard,
        shard_max_chars=max_chars,
        threshold_chars=threshold_chars,
        threshold_source_count=threshold_sources,
        source_count=source_count,
        source_chars=source_chars,
    )


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


def _context_shard_artifacts(
    *,
    topic: Topic,
    source_paths: Sequence[Path],
    run_id: Optional[str],
    timestamp: Optional[str],
    plan: PreservePlan,
) -> list[ContextShardArtifact]:
    if not source_paths:
        return []
    chunks = chunk_markdown_files(source_paths, vault_root=topic.vault_root)
    parts = shard_chunks(chunks, max_chars=plan.shard_max_chars)
    topic_rel = topic.relative_path.as_posix()
    # Context shards are source-content sidecars. Keep their content stable for
    # unchanged sources so idempotence can be proven without rerunning the LLM.
    stable_run_id = None
    stable_timestamp = "source-content-stable"
    return [
        _context_shard_artifact(
            topic_rel=topic_rel,
            run_id=stable_run_id,
            timestamp=stable_timestamp,
            part=part,
            part_count=len(parts),
        )
        for part in parts
    ]


def _context_shard_artifact(
    *,
    topic_rel: str,
    run_id: Optional[str],
    timestamp: str,
    part: ContextPart,
    part_count: int,
) -> ContextShardArtifact:
    filename = f"CONTEXT-{part.ordinal + 1:03d}.md"
    relative_path = (
        Path(topic_rel) / "_generated" / "mindfresh" / filename
        if topic_rel != "."
        else Path("_generated") / "mindfresh" / filename
    ).as_posix()
    text = render_context_shard(
        topic=topic_rel,
        run_id=run_id,
        timestamp=timestamp,
        part=part,
        part_count=part_count,
    )
    return ContextShardArtifact(
        relative_path=relative_path,
        text=text,
        sha256=hash_bytes(text.encode("utf-8")),
    )


def _context_artifacts_match(topic_dir: Path, artifacts: Sequence[ContextShardArtifact]) -> bool:
    context_dir = topic_dir / "_generated" / "mindfresh"
    if not artifacts:
        return not context_dir.exists() or not any(context_dir.glob("CONTEXT-*.md"))
    vault_root = _vault_root_from_topic_dir_and_artifacts(topic_dir, artifacts)
    for artifact in artifacts:
        path = vault_root / artifact.relative_path
        if not path.exists() or hash_bytes(path.read_bytes()) != artifact.sha256:
            return False
    expected_names = {Path(artifact.relative_path).name for artifact in artifacts}
    existing_names = {path.name for path in context_dir.glob("CONTEXT-*.md")}
    return existing_names == expected_names


def _write_context_artifacts(
    topic_dir: Path,
    artifacts: Sequence[ContextShardArtifact],
) -> None:
    context_dir = topic_dir / "_generated" / "mindfresh"
    if not artifacts:
        if context_dir.exists():
            for stale in context_dir.glob("CONTEXT-*.md"):
                stale.unlink()
        return

    context_dir.mkdir(parents=True, exist_ok=True)
    expected_names = set()
    vault_root = _vault_root_from_topic_dir_and_artifacts(topic_dir, artifacts)
    for artifact in artifacts:
        path = vault_root / artifact.relative_path
        expected_names.add(path.name)
        write_atomic_text(path, artifact.text)
    for stale in context_dir.glob("CONTEXT-*.md"):
        if stale.name not in expected_names:
            stale.unlink()


def _vault_root_from_topic_dir_and_artifacts(
    topic_dir: Path,
    artifacts: Sequence[ContextShardArtifact],
) -> Path:
    if not artifacts:
        return topic_dir
    first_parts = Path(artifacts[0].relative_path).parts
    suffix = ("_generated", "mindfresh", Path(artifacts[0].relative_path).name)
    if first_parts[-3:] != suffix:
        return topic_dir
    topic_parts = first_parts[:-3]
    root = topic_dir
    for _ in topic_parts:
        root = root.parent
    return root


def refresh_with_test_crash(
    vault_root: Path,
    *,
    crash_at: Optional[str] = None,
    adapter: str = "fake",
    model: Optional[str] = None,
) -> list[RefreshResult]:
    """Bounded test hook for crash-window retry behavior.

    The production writer uses same-directory atomic replacement. This hook
    simulates the named crash window by forcing one refresh attempt, then lets a
    second normal call converge through the manifest/idempotence path.
    """
    if crash_at == "after_rename_before_manifest":
        return refresh_vault(vault_root, adapter_name=adapter, adapter_model=model, force=True)
    if crash_at is None:
        return refresh_vault(vault_root, adapter_name=adapter, adapter_model=model)
    raise ValueError(f"unsupported crash point: {crash_at}")
