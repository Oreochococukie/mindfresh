from __future__ import annotations

from pathlib import Path

from mindfresh.scanner import collect_topic_sources, detect_topics, is_source_markdown

from conftest import create_fixture_vault, markdown_hashes, raw_markdown_files


def test_scanner_excludes_generated_internal_hidden_and_review_files(tmp_path: Path) -> None:
    fixture = create_fixture_vault(tmp_path)
    topic-a = fixture.topic-a
    (topic-a / "SUMMARY.md").write_text("# generated summary\n", encoding="utf-8")
    (topic-a / "CHANGELOG.md").write_text("# generated changelog\n", encoding="utf-8")
    (topic-a / "generated-frontmatter.md").write_text(
        "---\nmindfresh_generated: true\n---\n# generated body\n", encoding="utf-8"
    )
    (fixture.root / ".mindfresh").mkdir()
    (fixture.root / ".mindfresh" / "manifest-note.md").write_text("# internal\n", encoding="utf-8")
    (topic-a / ".hidden").mkdir()
    (topic-a / ".hidden" / "secret.md").write_text("# hidden\n", encoding="utf-8")
    (topic-a / "_generated").mkdir()
    (topic-a / "_generated" / "draft.md").write_text("# generated\n", encoding="utf-8")
    (topic-a / "_review").mkdir()
    (topic-a / "_review" / "review.md").write_text("# review\n", encoding="utf-8")

    topics = detect_topics(fixture.root)
    topic_paths = [topic.relative_path.as_posix() for topic in topics]
    assert topic_paths == ["policy/policy-platform", "research/topic-a", "research/topic-b"]

    topic-a_topic = next(topic for topic in topics if topic.relative_path.as_posix() == "research/topic-a")
    source_names = [path.name for path in collect_topic_sources(topic-a_topic)]
    assert source_names == ["2026-04-01-baseline.md", "2026-04-20-comparison.md"]
    assert not is_source_markdown(topic-a / "generated-frontmatter.md")


def test_generated_outputs_are_never_reingested_after_creation(tmp_path: Path) -> None:
    fixture = create_fixture_vault(tmp_path)
    (fixture.topic-a / "SUMMARY.md").write_text(
        "---\nmindfresh_generated: true\nmindfresh_kind: summary\n---\n"
        "# Summary\n\nThis generated file contains rich markdown that must not be a source.\n",
        encoding="utf-8",
    )
    (fixture.topic-a / "CHANGELOG.md").write_text(
        "---\nmindfresh_generated: true\nmindfresh_kind: changelog\n---\n"
        "## Run\n- Generated content\n",
        encoding="utf-8",
    )

    topic-a_topic = next(
        topic
        for topic in detect_topics(fixture.root)
        if topic.relative_path.as_posix() == "research/topic-a"
    )

    assert {path.name for path in collect_topic_sources(topic-a_topic)} == {
        "2026-04-01-baseline.md",
        "2026-04-20-comparison.md",
    }


def test_scanner_and_source_collection_do_not_modify_raw_notes(tmp_path: Path) -> None:
    fixture = create_fixture_vault(tmp_path)
    before = markdown_hashes(raw_markdown_files(fixture.root))

    topics = detect_topics(fixture.root)
    for topic in topics:
        collect_topic_sources(topic)

    after = markdown_hashes(raw_markdown_files(fixture.root))
    assert after == before
