from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple
from uuid import uuid4
from datetime import datetime, timezone

from .scanner import HASH_ALGORITHM, SourceSnapshot

SCHEMA_VERSION = 1
MANIFEST_DIR_NAME = ".mindfresh"
MANIFEST_FILE_NAME = "manifest.sqlite"


@dataclass(frozen=True)
class SourceChange:
    relative_path: Path
    kind: str
    before_sha256: Optional[str]
    after_sha256: Optional[str]


@dataclass(frozen=True)
class GeneratedArtifact:
    relative_path: Path
    before_sha256: Optional[str]
    after_sha256: Optional[str]


@dataclass(frozen=True)
class RefreshPlan:
    topic_path: Path
    config_hash: str
    invalidation_key: str
    previous_invalidation_key: Optional[str]
    source_changes: Tuple[SourceChange, ...]
    config_changed: bool
    is_noop: bool
    trigger_reason: str


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    topic_path: Path
    config_hash: str
    invalidation_key: str
    trigger_reason: str
    no_op: bool


def manifest_path(vault_root: Path) -> Path:
    return Path(vault_root).expanduser().resolve() / MANIFEST_DIR_NAME / MANIFEST_FILE_NAME


def connect_manifest(vault_root: Path) -> sqlite3.Connection:
    path = manifest_path(vault_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    return conn


def hash_config_profile(
    *,
    prompt_schema_version: str,
    adapter_name: str,
    model_profile: str,
    adapter_config: Optional[Mapping[str, Any]] = None,
) -> str:
    payload = {
        "adapter_config": adapter_config or {},
        "adapter_name": adapter_name,
        "hash_algorithm": HASH_ALGORITHM,
        "model_profile": model_profile,
        "prompt_schema_version": prompt_schema_version,
        "schema_version": SCHEMA_VERSION,
    }
    return _hash_json(payload)


def compute_invalidation_key(config_hash: str, sources: Sequence[SourceSnapshot]) -> str:
    payload = {
        "config_hash": config_hash,
        "hash_algorithm": HASH_ALGORITHM,
        "schema_version": SCHEMA_VERSION,
        "sources": [
            {"path": source.relative_path.as_posix(), "sha256": source.sha256}
            for source in sorted(sources, key=lambda item: item.relative_path.as_posix())
        ],
    }
    return _hash_json(payload)


def plan_refresh(
    vault_root: Path,
    *,
    topic_path: Path,
    sources: Sequence[SourceSnapshot],
    config_hash: str,
    force: bool = False,
) -> RefreshPlan:
    topic_key = _path_key(topic_path)
    invalidation_key = compute_invalidation_key(config_hash, sources)

    with connect_manifest(vault_root) as conn:
        previous_sources = _load_sources(conn, topic_key)
        state = conn.execute(
            "SELECT config_hash, invalidation_key FROM topic_state WHERE topic_path = ?",
            (topic_key,),
        ).fetchone()

    incoming = {source.relative_path.as_posix(): source for source in sources}
    changes: List[SourceChange] = []
    for relative_path, source in sorted(incoming.items()):
        before_hash = previous_sources.get(relative_path)
        if before_hash is None:
            kind = "new"
        elif before_hash != source.sha256:
            kind = "modified"
        else:
            continue
        changes.append(
            SourceChange(
                relative_path=Path(relative_path),
                kind=kind,
                before_sha256=before_hash,
                after_sha256=source.sha256,
            )
        )

    for relative_path, before_hash in sorted(previous_sources.items()):
        if relative_path not in incoming:
            changes.append(
                SourceChange(
                    relative_path=Path(relative_path),
                    kind="deleted",
                    before_sha256=before_hash,
                    after_sha256=None,
                )
            )

    previous_config_hash = str(state["config_hash"]) if state is not None else None
    previous_invalidation_key = str(state["invalidation_key"]) if state is not None else None
    config_changed = previous_config_hash is not None and previous_config_hash != config_hash
    is_noop = (
        not force
        and not changes
        and previous_config_hash == config_hash
        and previous_invalidation_key == invalidation_key
    )

    if force:
        trigger_reason = "forced"
    elif previous_invalidation_key is None:
        trigger_reason = "first_run"
    elif changes:
        trigger_reason = "source_changed"
    elif config_changed or previous_invalidation_key != invalidation_key:
        trigger_reason = "config_changed"
    else:
        trigger_reason = "noop"

    return RefreshPlan(
        topic_path=Path(topic_key),
        config_hash=config_hash,
        invalidation_key=invalidation_key,
        previous_invalidation_key=previous_invalidation_key,
        source_changes=tuple(changes),
        config_changed=config_changed,
        is_noop=is_noop,
        trigger_reason=trigger_reason,
    )


def record_refresh_result(
    vault_root: Path,
    *,
    topic_path: Path,
    sources: Sequence[SourceSnapshot],
    config_hash: str,
    generated_artifacts: Iterable[GeneratedArtifact] = (),
    run_id: Optional[str] = None,
    no_op: Optional[bool] = None,
    force: bool = False,
    prompt_schema_version: Optional[str] = None,
    adapter_name: Optional[str] = None,
    model_profile: Optional[str] = None,
    adapter_config: Optional[Mapping[str, Any]] = None,
) -> RunRecord:
    plan = plan_refresh(
        vault_root,
        topic_path=topic_path,
        sources=sources,
        config_hash=config_hash,
        force=force,
    )
    resolved_no_op = plan.is_noop if no_op is None else no_op
    resolved_run_id = run_id or uuid4().hex
    now = _utc_now()
    topic_key = _path_key(topic_path)
    source_keys = {source.relative_path.as_posix() for source in sources}
    artifacts = tuple(generated_artifacts)

    with connect_manifest(vault_root) as conn:
        conn.execute("BEGIN")
        conn.execute(
            """
            INSERT INTO runs (
                run_id, topic_path, started_at, completed_at, status, trigger_reason,
                config_hash, invalidation_key, no_op
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_run_id,
                topic_key,
                now,
                now,
                "completed",
                plan.trigger_reason,
                config_hash,
                plan.invalidation_key,
                1 if resolved_no_op else 0,
            ),
        )

        for source in sources:
            rel = source.relative_path.as_posix()
            change = _change_kind_for(rel, plan.source_changes)
            conn.execute(
                """
                INSERT INTO sources (topic_path, relative_path, sha256, size, mtime_ns, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_path, relative_path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    size = excluded.size,
                    mtime_ns = excluded.mtime_ns,
                    updated_at = excluded.updated_at
                """,
                (topic_key, rel, source.sha256, source.size, source.mtime_ns, now),
            )
            conn.execute(
                """
                INSERT INTO run_sources (run_id, relative_path, sha256, change_kind)
                VALUES (?, ?, ?, ?)
                """,
                (resolved_run_id, rel, source.sha256, change),
            )

        for removed in sorted(_load_sources(conn, topic_key)):
            if removed in source_keys:
                continue
            conn.execute(
                "DELETE FROM sources WHERE topic_path = ? AND relative_path = ?",
                (topic_key, removed),
            )
            conn.execute(
                """
                INSERT INTO run_sources (run_id, relative_path, sha256, change_kind)
                VALUES (?, ?, ?, ?)
                """,
                (resolved_run_id, removed, None, "deleted"),
            )

        for artifact in artifacts:
            rel = _path_key(artifact.relative_path)
            conn.execute(
                """
                INSERT INTO run_generated (run_id, relative_path, before_sha256, after_sha256)
                VALUES (?, ?, ?, ?)
                """,
                (resolved_run_id, rel, artifact.before_sha256, artifact.after_sha256),
            )
            if artifact.after_sha256 is not None:
                conn.execute(
                    """
                    INSERT INTO generated_artifacts (topic_path, relative_path, sha256, updated_at, last_run_id)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(topic_path, relative_path) DO UPDATE SET
                        sha256 = excluded.sha256,
                        updated_at = excluded.updated_at,
                        last_run_id = excluded.last_run_id
                    """,
                    (topic_key, rel, artifact.after_sha256, now, resolved_run_id),
                )

        if prompt_schema_version is not None or adapter_name is not None or model_profile is not None:
            adapter_config_json = _stable_json(adapter_config or {})
            conn.execute(
                """
                INSERT INTO config_profiles (
                    config_hash, prompt_schema_version, adapter_name, model_profile,
                    adapter_config_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(config_hash) DO UPDATE SET
                    prompt_schema_version = excluded.prompt_schema_version,
                    adapter_name = excluded.adapter_name,
                    model_profile = excluded.model_profile,
                    adapter_config_json = excluded.adapter_config_json,
                    updated_at = excluded.updated_at
                """,
                (
                    config_hash,
                    prompt_schema_version,
                    adapter_name,
                    model_profile,
                    adapter_config_json,
                    now,
                ),
            )

        conn.execute(
            """
            INSERT INTO topic_state (
                topic_path, config_hash, invalidation_key, last_run_id, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_path) DO UPDATE SET
                config_hash = excluded.config_hash,
                invalidation_key = excluded.invalidation_key,
                last_run_id = excluded.last_run_id,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                topic_key,
                config_hash,
                plan.invalidation_key,
                resolved_run_id,
                "noop" if resolved_no_op else "fresh",
                now,
            ),
        )
        conn.commit()

    return RunRecord(
        run_id=resolved_run_id,
        topic_path=Path(topic_key),
        config_hash=config_hash,
        invalidation_key=plan.invalidation_key,
        trigger_reason=plan.trigger_reason,
        no_op=resolved_no_op,
    )


def current_generated_hashes(vault_root: Path, *, topic_path: Path) -> Mapping[str, str]:
    topic_key = _path_key(topic_path)
    with connect_manifest(vault_root) as conn:
        rows = conn.execute(
            "SELECT relative_path, sha256 FROM generated_artifacts WHERE topic_path = ?",
            (topic_key,),
        ).fetchall()
    return {str(row["relative_path"]): str(row["sha256"]) for row in rows}


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sources (
            topic_path TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (topic_path, relative_path)
        );

        CREATE TABLE IF NOT EXISTS generated_artifacts (
            topic_path TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_run_id TEXT NOT NULL,
            PRIMARY KEY (topic_path, relative_path)
        );

        CREATE TABLE IF NOT EXISTS config_profiles (
            config_hash TEXT PRIMARY KEY,
            prompt_schema_version TEXT,
            adapter_name TEXT,
            model_profile TEXT,
            adapter_config_json TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS topic_state (
            topic_path TEXT PRIMARY KEY,
            config_hash TEXT NOT NULL,
            invalidation_key TEXT NOT NULL,
            last_run_id TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            topic_path TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            status TEXT NOT NULL,
            trigger_reason TEXT NOT NULL,
            config_hash TEXT NOT NULL,
            invalidation_key TEXT NOT NULL,
            no_op INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS run_sources (
            run_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            sha256 TEXT,
            change_kind TEXT NOT NULL,
            PRIMARY KEY (run_id, relative_path),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS run_generated (
            run_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            before_sha256 TEXT,
            after_sha256 TEXT,
            PRIMARY KEY (run_id, relative_path),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ("hash_algorithm", HASH_ALGORITHM),
    )
    schema_version = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()["value"]
    hash_algorithm = conn.execute(
        "SELECT value FROM meta WHERE key = 'hash_algorithm'"
    ).fetchone()["value"]
    if schema_version != str(SCHEMA_VERSION):
        raise RuntimeError(f"unsupported manifest schema version: {schema_version}")
    if hash_algorithm != HASH_ALGORITHM:
        raise RuntimeError(f"unsupported manifest hash algorithm: {hash_algorithm}")
    conn.commit()


def _load_sources(conn: sqlite3.Connection, topic_key: str) -> Mapping[str, str]:
    rows = conn.execute(
        "SELECT relative_path, sha256 FROM sources WHERE topic_path = ?",
        (topic_key,),
    ).fetchall()
    return {str(row["relative_path"]): str(row["sha256"]) for row in rows}


def _change_kind_for(relative_path: str, changes: Sequence[SourceChange]) -> str:
    for change in changes:
        if change.relative_path.as_posix() == relative_path:
            return change.kind
    return "unchanged"


def _path_key(path: Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError(f"manifest paths must be vault-relative: {path}")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"manifest paths cannot escape the vault: {path}")
    value = candidate.as_posix()
    return "." if value in {"", "."} else value


def _hash_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _stable_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TopicRunSource:
    relative_path: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class TopicRunState:
    source_fingerprint: str
    invalidation_key: str
    summary_hash: str
    changelog_hash: str
    source_hashes: Mapping[str, str]


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_file(path: Path, *, relative_to: Path) -> TopicRunSource:
    stat = path.stat()
    return TopicRunSource(
        relative_path=path.relative_to(relative_to).as_posix(),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=hash_bytes(path.read_bytes()),
    )


def source_fingerprint(sources: Sequence[object]) -> str:
    payload = [
        {"path": _source_relative(source), "sha256": _source_sha(source), "size": _source_size(source)}
        for source in sorted(sources, key=_source_relative)
    ]
    return hash_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def invalidation_key(
    *,
    adapter_name: str,
    model_profile: str,
    source_hashes: Mapping[str, str],
) -> str:
    from .schemas import PROMPT_SCHEMA_VERSION

    payload = {
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "adapter_name": adapter_name,
        "model_profile": model_profile,
        "source_hashes": dict(sorted(source_hashes.items())),
    }
    return hash_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def connect(vault_root: Path) -> sqlite3.Connection:
    return connect_manifest(vault_root)


def load_topic_state(conn: sqlite3.Connection, topic_path: str) -> Optional[TopicRunState]:
    topic_key = _path_key(Path(topic_path))
    row = conn.execute(
        "SELECT invalidation_key FROM topic_state WHERE topic_path = ?",
        (topic_key,),
    ).fetchone()
    if row is None:
        return None

    source_rows = conn.execute(
        "SELECT relative_path, sha256, size, mtime_ns FROM sources WHERE topic_path = ?",
        (topic_key,),
    ).fetchall()
    sources = [
        TopicRunSource(
            relative_path=str(item["relative_path"]),
            sha256=str(item["sha256"]),
            size=int(item["size"]),
            mtime_ns=int(item["mtime_ns"]),
        )
        for item in source_rows
    ]
    source_hashes = {source.relative_path: source.sha256 for source in sources}
    generated = _load_generated(conn, topic_key)
    return TopicRunState(
        source_fingerprint=source_fingerprint(sources),
        invalidation_key=str(row["invalidation_key"]),
        summary_hash=generated.get(_generated_artifact_path(topic_key, "SUMMARY.md"), ""),
        changelog_hash=generated.get(_generated_artifact_path(topic_key, "CHANGELOG.md"), ""),
        source_hashes=source_hashes,
    )


def record_topic_run(
    conn: sqlite3.Connection,
    *,
    topic_path: str,
    run_id: str,
    timestamp: str,
    sources: Sequence[object],
    source_fingerprint_value: str,
    invalidation_key_value: str,
    summary_hash: str,
    changelog_hash: str,
    adapter_name: str,
    model_profile: str,
) -> None:
    from .schemas import PROMPT_SCHEMA_VERSION

    topic_key = _path_key(Path(topic_path))
    config_hash = hash_config_profile(
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        adapter_name=adapter_name,
        model_profile=model_profile,
    )
    source_keys = {_source_relative(source) for source in sources}
    summary_rel = _generated_artifact_path(topic_key, "SUMMARY.md")
    changelog_rel = _generated_artifact_path(topic_key, "CHANGELOG.md")
    previous_generated = _load_generated(conn, topic_key)

    with conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, topic_path, started_at, completed_at, status, trigger_reason,
                config_hash, invalidation_key, no_op
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                topic_key,
                timestamp,
                timestamp,
                "completed",
                "refresh",
                config_hash,
                invalidation_key_value,
                0,
            ),
        )
        for source in sources:
            rel = _source_relative(source)
            conn.execute(
                """
                INSERT INTO sources (topic_path, relative_path, sha256, size, mtime_ns, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_path, relative_path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    size = excluded.size,
                    mtime_ns = excluded.mtime_ns,
                    updated_at = excluded.updated_at
                """,
                (topic_key, rel, _source_sha(source), _source_size(source), _source_mtime_ns(source), timestamp),
            )
            conn.execute(
                """
                INSERT INTO run_sources (run_id, relative_path, sha256, change_kind)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, rel, _source_sha(source), "unchanged"),
            )

        for removed in sorted(_load_sources(conn, topic_key)):
            if removed in source_keys:
                continue
            conn.execute(
                "DELETE FROM sources WHERE topic_path = ? AND relative_path = ?",
                (topic_key, removed),
            )
            conn.execute(
                """
                INSERT INTO run_sources (run_id, relative_path, sha256, change_kind)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, removed, None, "deleted"),
            )

        for rel, after_hash in ((summary_rel, summary_hash), (changelog_rel, changelog_hash)):
            before_hash = previous_generated.get(rel)
            conn.execute(
                """
                INSERT INTO run_generated (run_id, relative_path, before_sha256, after_sha256)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, rel, before_hash, after_hash),
            )
            conn.execute(
                """
                INSERT INTO generated_artifacts (topic_path, relative_path, sha256, updated_at, last_run_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(topic_path, relative_path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    updated_at = excluded.updated_at,
                    last_run_id = excluded.last_run_id
                """,
                (topic_key, rel, after_hash, timestamp, run_id),
            )

        conn.execute(
            """
            INSERT INTO config_profiles (
                config_hash, prompt_schema_version, adapter_name, model_profile,
                adapter_config_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(config_hash) DO UPDATE SET
                prompt_schema_version = excluded.prompt_schema_version,
                adapter_name = excluded.adapter_name,
                model_profile = excluded.model_profile,
                adapter_config_json = excluded.adapter_config_json,
                updated_at = excluded.updated_at
            """,
            (config_hash, PROMPT_SCHEMA_VERSION, adapter_name, model_profile, "{}", timestamp),
        )
        conn.execute(
            """
            INSERT INTO topic_state (
                topic_path, config_hash, invalidation_key, last_run_id, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_path) DO UPDATE SET
                config_hash = excluded.config_hash,
                invalidation_key = excluded.invalidation_key,
                last_run_id = excluded.last_run_id,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (topic_key, config_hash, invalidation_key_value, run_id, "fresh", timestamp),
        )


def _load_generated(conn: sqlite3.Connection, topic_key: str) -> Mapping[str, str]:
    rows = conn.execute(
        "SELECT relative_path, sha256 FROM generated_artifacts WHERE topic_path = ?",
        (topic_key,),
    ).fetchall()
    return {str(row["relative_path"]): str(row["sha256"]) for row in rows}


def _generated_artifact_path(topic_key: str, filename: str) -> str:
    return filename if topic_key == "." else f"{topic_key}/{filename}"


def _source_relative(source: object) -> str:
    rel = getattr(source, "relative_path")
    return rel.as_posix() if hasattr(rel, "as_posix") else str(rel)


def _source_sha(source: object) -> str:
    return str(getattr(source, "sha256"))


def _source_size(source: object) -> int:
    return int(getattr(source, "size"))


def _source_mtime_ns(source: object) -> int:
    return int(getattr(source, "mtime_ns"))
