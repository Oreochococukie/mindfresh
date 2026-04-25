from pathlib import Path

import pytest

from mindfresh.scanner import (
    assert_source_hashes_unchanged,
    capture_source_hashes,
    collect_topic_source_snapshots,
    collect_topic_sources,
    detect_topics,
    hash_file,
)


def test_detects_topics_and_ignores_generated(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    topic = vault / "research" / "topic_a"
    topic.mkdir(parents=True)
    (topic / "a.md").write_text("# note", encoding="utf-8")
    (topic / "SUMMARY.md").write_text("# generated", encoding="utf-8")
    (topic / "CHANGELOG.md").write_text("# generated", encoding="utf-8")

    topics = detect_topics(vault)
    assert len(topics) == 1
    assert topics[0].relative_path.as_posix() == "research/topic_a"
    srcs = collect_topic_sources(topics[0])
    assert len(srcs) == 1
    assert srcs[0].name == "a.md"


def test_scanner_prunes_hidden_internal_and_generated_boundaries(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    topic = vault / "research" / "topic_a"
    topic.mkdir(parents=True)
    (topic / "raw.md").write_text("# source", encoding="utf-8")
    (topic / "generated-frontmatter.md").write_text(
        "---\nmindfresh_generated: true\n---\n# generated", encoding="utf-8"
    )
    (topic / "SUMMARY.md").write_text("# generated", encoding="utf-8")
    (topic / "CHANGELOG.md").write_text("# generated", encoding="utf-8")
    (vault / ".mindfresh").mkdir()
    (vault / ".mindfresh" / "internal.md").write_text("# internal", encoding="utf-8")
    (topic / ".notes").mkdir()
    (topic / ".notes" / "hidden.md").write_text("# hidden", encoding="utf-8")
    (topic / "_generated").mkdir()
    (topic / "_generated" / "draft.md").write_text("# generated draft", encoding="utf-8")
    (topic / "_review").mkdir()
    (topic / "_review" / "review.md").write_text("# review", encoding="utf-8")

    topics = detect_topics(vault)
    assert [topic.relative_path.as_posix() for topic in topics] == ["research/topic_a"]
    sources = collect_topic_sources(topics[0])
    assert [source.name for source in sources] == ["raw.md"]

    snapshots = collect_topic_source_snapshots(topics[0])
    assert len(snapshots) == 1
    assert snapshots[0].relative_path.as_posix() == "research/topic_a/raw.md"
    assert snapshots[0].sha256 == hash_file(topic / "raw.md")
    assert snapshots[0].size == len("# source")


def test_raw_hash_capture_detects_source_mutation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    topic = vault / "topic"
    topic.mkdir(parents=True)
    source = topic / "raw.md"
    source.write_text("original", encoding="utf-8")
    before = capture_source_hashes([source], vault_root=vault)

    assert_source_hashes_unchanged(before, vault_root=vault)

    source.write_text("modified", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed=topic/raw.md"):
        assert_source_hashes_unchanged(before, vault_root=vault)
