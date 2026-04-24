from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import uuid

from .adapters import SourceDocument, get_adapter
from .manifest import (
    connect,
    hash_bytes,
    invalidation_key,
    load_topic_state,
    record_topic_run,
    snapshot_file,
    source_fingerprint,
)
from .scanner import Topic, collect_topic_sources, detect_topics
from .schemas import ChangelogEntry, SourceRef, render_changelog, render_summary
from .writer import write_atomic_text


@dataclass(frozen=True)
class RefreshResult:
    topic: str
    status: str
    run_id: Optional[str]
    summary_hash: Optional[str]
    changelog_hash: Optional[str]
    trigger_files: Sequence[str]


def refresh_vault(
    vault_root: Path,
    *,
    topic: Optional[str] = None,
    adapter_name: str = "fake",
    adapter_model: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
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
    conn: Optional[object] = None,
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
            conn=connection,  # type: ignore[arg-type]
        )
    finally:
        if owns_connection:
            connection.close()  # type: ignore[attr-defined]


def _refresh_topic_with_connection(
    topic: Topic,
    *,
    adapter_name: str,
    adapter_model: Optional[str],
    model_profile: str,
    dry_run: bool,
    force: bool,
    conn: object,
) -> RefreshResult:
    adapter = get_adapter(adapter_name, model=adapter_model)
    topic_rel = topic.relative_path.as_posix()
    topic_dir = topic.vault_root / topic.relative_path
    summary_path = topic_dir / "SUMMARY.md"
    changelog_path = topic_dir / "CHANGELOG.md"

    source_paths = collect_topic_sources(topic)
    before = [snapshot_file(path, relative_to=topic.vault_root) for path in source_paths]
    before_by_path = {src.relative_path: src.sha256 for src in before}
    fingerprint = source_fingerprint(before)
    key = invalidation_key(
        adapter_name=adapter.name,
        model_profile=adapter.model_profile,
        source_hashes=before_by_path,
    )
    state = load_topic_state(conn, topic_rel)  # type: ignore[arg-type]

    if (
        state is not None
        and not force
        and _generated_matches_state(summary_path, changelog_path, state)
    ):
        if state.invalidation_key == key and state.source_fingerprint == fingerprint:
            return RefreshResult(
                topic=topic_rel,
                status="unchanged",
                run_id=None,
                summary_hash=state.summary_hash,
                changelog_hash=state.changelog_hash,
                trigger_files=[],
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

    summary = render_summary(
        topic=topic_rel,
        run_id=run_id,
        timestamp=timestamp,
        result=result,
        source_refs=source_refs,
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
        )

    _, summary_hash = write_atomic_text(summary_path, summary)
    _, changelog_hash = write_atomic_text(changelog_path, changelog)

    after = [snapshot_file(path, relative_to=topic.vault_root) for path in source_paths]
    after_by_path = {src.relative_path: src.sha256 for src in after}
    if after_by_path != before_by_path:
        raise RuntimeError(f"raw source changed during refresh for topic: {topic_rel}")

    record_topic_run(
        conn,  # type: ignore[arg-type]
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


def _recent_source_paths(current: Sequence[object], previous_hashes: dict[str, str]) -> set[str]:
    changed: set[str] = set()
    for src in current:
        relative_path = getattr(src, "relative_path")
        sha256 = getattr(src, "sha256")
        if previous_hashes.get(relative_path) != sha256:
            changed.add(relative_path)
    return changed


def _generated_matches_state(summary_path: Path, changelog_path: Path, state: object) -> bool:
    if not summary_path.exists() or not changelog_path.exists():
        return False
    return (
        hash_bytes(summary_path.read_bytes()) == getattr(state, "summary_hash")
        and hash_bytes(changelog_path.read_bytes()) == getattr(state, "changelog_hash")
    )


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
