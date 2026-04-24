from __future__ import annotations

from pathlib import Path
import sqlite3

from mindfresh.manifest import (
    GeneratedArtifact,
    compute_invalidation_key,
    connect_manifest,
    current_generated_hashes,
    hash_config_profile,
    manifest_path,
    plan_refresh,
    record_refresh_result,
)
from mindfresh.scanner import SourceSnapshot, Topic, collect_topic_source_snapshots, detect_topics, hash_file


def _make_vault(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    topic = vault / "research" / "topic-a"
    topic.mkdir(parents=True)
    (topic / "raw.md").write_text("# raw", encoding="utf-8")
    return vault, topic


def _topic_and_sources(vault: Path) -> tuple[Topic, list[SourceSnapshot]]:
    topic = detect_topics(vault)[0]
    return topic, collect_topic_source_snapshots(topic)


def test_manifest_initializes_per_vault_schema_and_meta(tmp_path: Path) -> None:
    vault_a, _ = _make_vault(tmp_path / "a")
    vault_b, _ = _make_vault(tmp_path / "b")

    with connect_manifest(vault_a) as conn:
        rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())

    assert manifest_path(vault_a) == vault_a.resolve() / ".mindfresh" / "manifest.sqlite"
    assert manifest_path(vault_b) == vault_b.resolve() / ".mindfresh" / "manifest.sqlite"
    assert manifest_path(vault_a) != manifest_path(vault_b)
    assert rows["schema_version"] == "1"
    assert rows["hash_algorithm"] == "sha256"


def test_manifest_detects_first_run_noop_source_and_config_changes(tmp_path: Path) -> None:
    vault, topic_dir = _make_vault(tmp_path)
    topic, sources = _topic_and_sources(vault)
    config_hash = hash_config_profile(
        prompt_schema_version="summary-v1",
        adapter_name="fake",
        model_profile="ci",
        adapter_config={"temperature": 0},
    )

    first_plan = plan_refresh(
        vault,
        topic_path=topic.relative_path,
        sources=sources,
        config_hash=config_hash,
    )
    assert first_plan.trigger_reason == "first_run"
    assert first_plan.is_noop is False
    assert [change.kind for change in first_plan.source_changes] == ["new"]

    summary = topic_dir / "SUMMARY.md"
    changelog = topic_dir / "CHANGELOG.md"
    summary.write_text("summary", encoding="utf-8")
    changelog.write_text("changelog", encoding="utf-8")
    record = record_refresh_result(
        vault,
        topic_path=topic.relative_path,
        sources=sources,
        config_hash=config_hash,
        generated_artifacts=(
            GeneratedArtifact(Path("research/topic-a/SUMMARY.md"), None, hash_file(summary)),
            GeneratedArtifact(Path("research/topic-a/CHANGELOG.md"), None, hash_file(changelog)),
        ),
        prompt_schema_version="summary-v1",
        adapter_name="fake",
        model_profile="ci",
        adapter_config={"temperature": 0},
    )
    assert record.trigger_reason == "first_run"
    assert record.no_op is False
    assert record.invalidation_key == compute_invalidation_key(config_hash, sources)

    with sqlite3.connect(manifest_path(vault)) as conn:
        config_profile = conn.execute(
            "SELECT adapter_config_json FROM config_profiles WHERE config_hash = ?",
            (config_hash,),
        ).fetchone()
    assert config_profile[0] == '{"temperature":0}'

    hashes = current_generated_hashes(vault, topic_path=topic.relative_path)
    assert hashes["research/topic-a/SUMMARY.md"] == hash_file(summary)
    assert hashes["research/topic-a/CHANGELOG.md"] == hash_file(changelog)

    noop_plan = plan_refresh(
        vault,
        topic_path=topic.relative_path,
        sources=sources,
        config_hash=config_hash,
    )
    assert noop_plan.trigger_reason == "noop"
    assert noop_plan.is_noop is True
    assert noop_plan.source_changes == ()

    record_noop = record_refresh_result(
        vault,
        topic_path=topic.relative_path,
        sources=sources,
        config_hash=config_hash,
    )
    assert record_noop.trigger_reason == "noop"
    assert record_noop.no_op is True

    (topic_dir / "raw.md").write_text("# changed", encoding="utf-8")
    _, changed_sources = _topic_and_sources(vault)
    changed_plan = plan_refresh(
        vault,
        topic_path=topic.relative_path,
        sources=changed_sources,
        config_hash=config_hash,
    )
    assert changed_plan.trigger_reason == "source_changed"
    assert [(change.relative_path.as_posix(), change.kind) for change in changed_plan.source_changes] == [
        ("research/topic-a/raw.md", "modified")
    ]

    new_config_hash = hash_config_profile(
        prompt_schema_version="summary-v2",
        adapter_name="fake",
        model_profile="ci",
        adapter_config={"temperature": 0},
    )
    record_refresh_result(
        vault,
        topic_path=topic.relative_path,
        sources=changed_sources,
        config_hash=config_hash,
    )
    config_plan = plan_refresh(
        vault,
        topic_path=topic.relative_path,
        sources=changed_sources,
        config_hash=new_config_hash,
    )
    assert config_plan.trigger_reason == "config_changed"
    assert config_plan.config_changed is True
    assert config_plan.is_noop is False


def test_manifest_records_run_history_sources_and_generated_before_after(tmp_path: Path) -> None:
    vault, topic_dir = _make_vault(tmp_path)
    topic, sources = _topic_and_sources(vault)
    config_hash = hash_config_profile(
        prompt_schema_version="summary-v1", adapter_name="fake", model_profile="ci"
    )
    summary = topic_dir / "SUMMARY.md"
    summary.write_text("summary", encoding="utf-8")

    record = record_refresh_result(
        vault,
        topic_path=topic.relative_path,
        sources=sources,
        config_hash=config_hash,
        generated_artifacts=(
            GeneratedArtifact(Path("research/topic-a/SUMMARY.md"), "0" * 64, hash_file(summary)),
        ),
        run_id="run-1",
    )

    with sqlite3.connect(manifest_path(vault)) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (record.run_id,)).fetchone()
        run_source = conn.execute(
            "SELECT relative_path, sha256, change_kind FROM run_sources WHERE run_id = ?",
            (record.run_id,),
        ).fetchone()
        run_generated = conn.execute(
            "SELECT relative_path, before_sha256, after_sha256 FROM run_generated WHERE run_id = ?",
            (record.run_id,),
        ).fetchone()

    assert run["topic_path"] == "research/topic-a"
    assert run["trigger_reason"] == "first_run"
    assert run["no_op"] == 0
    assert dict(run_source) == {
        "relative_path": "research/topic-a/raw.md",
        "sha256": sources[0].sha256,
        "change_kind": "new",
    }
    assert dict(run_generated) == {
        "relative_path": "research/topic-a/SUMMARY.md",
        "before_sha256": "0" * 64,
        "after_sha256": hash_file(summary),
    }
