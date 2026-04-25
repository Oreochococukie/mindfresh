from __future__ import annotations

from pathlib import Path

from mindfresh.chunker import chunk_markdown_file, chunk_markdown_files, shard_chunks
from mindfresh.refresh import refresh_vault


def test_heading_aware_chunks_include_source_metadata_and_hashes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    source = vault / "note.md"
    source.write_text(
        "\n".join(
            [
                "Preamble context.",
                "",
                "# Project Alpha",
                "",
                "Root detail.",
                "",
                "```",
                "# Not a heading",
                "```",
                "",
                "## Decision",
                "",
                "Nested decision detail.",
                "",
                "# Project Beta",
                "",
                "Other root detail.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    chunks = chunk_markdown_file(source, vault_root=vault)

    assert [chunk.source_path for chunk in chunks] == ["note.md", "note.md", "note.md", "note.md"]
    assert [chunk.heading_path for chunk in chunks] == [
        (),
        ("Project Alpha",),
        ("Project Alpha", "Decision"),
        ("Project Beta",),
    ]
    assert [chunk.ordinal for chunk in chunks] == [0, 1, 2, 3]
    assert "# Not a heading" in chunks[1].content
    assert all(chunk.char_count == len(chunk.content) for chunk in chunks)
    assert all(len(chunk.sha256) == 64 for chunk in chunks)


def test_large_vault_chunks_and_shards_preserve_unique_context(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    topic = vault / "research"
    topic.mkdir(parents=True)
    expected_sentinels = []

    for index in range(100):
        sentinel = f"SENTINEL_UNIQUE_CONTEXT_{index:03d}"
        expected_sentinels.append(sentinel)
        (topic / f"{index:03d}-note.md").write_text(
            "\n".join(
                [
                    f"# Topic {index:03d}",
                    "",
                    f"Stable overview for note {index:03d}.",
                    "",
                    "## Evidence",
                    "",
                    f"The unique context marker is {sentinel}.",
                    "",
                    "## Follow-up",
                    "",
                    f"Follow-up still belongs to note {index:03d}.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    chunks = chunk_markdown_files(topic.glob("*.md"), vault_root=vault)
    shards = shard_chunks(chunks, max_chars=5_000)

    assert len(chunks) == 300
    assert [chunk.source_path for chunk in chunks[:3]] == [
        "research/000-note.md",
        "research/000-note.md",
        "research/000-note.md",
    ]
    assert [chunk.heading_path for chunk in chunks[:3]] == [
        ("Topic 000",),
        ("Topic 000", "Evidence"),
        ("Topic 000", "Follow-up"),
    ]
    assert all(shard.char_count <= 5_000 for shard in shards)
    assert [shard.ordinal for shard in shards] == list(range(len(shards)))

    flattened_chunks = [chunk for shard in shards for chunk in shard.chunks]
    assert flattened_chunks == chunks

    rendered_context = "\n".join(shard.content for shard in shards)
    for sentinel in expected_sentinels:
        assert rendered_context.count(sentinel) == 1

    first_positions = [rendered_context.index(sentinel) for sentinel in expected_sentinels]
    assert first_positions == sorted(first_positions)


def test_refresh_sharded_mode_writes_context_parts_without_mutating_sources(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    topic = vault / "research" / "large-topic"
    topic.mkdir(parents=True)
    expected_sentinels = []
    for index in range(30):
        sentinel = f"REFRESH_SENTINEL_UNIQUE_CONTEXT_{index:03d}"
        expected_sentinels.append(sentinel)
        (topic / f"{index:03d}-source.md").write_text(
            f"# Source {index:03d}\n\nImportant non-overlap context: {sentinel}.\n",
            encoding="utf-8",
        )

    before = {path.name: path.read_text(encoding="utf-8") for path in topic.glob("*-source.md")}
    results = refresh_vault(
        vault,
        adapter_name="fake",
        preserve_mode="sharded",
        context_shard_max_chars=4_000,
    )

    assert results[0].status == "refreshed"
    assert results[0].context_hashes
    context_files = sorted((topic / "_generated" / "mindfresh").glob("CONTEXT-*.md"))
    assert context_files
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in context_files)
    for sentinel in expected_sentinels:
        assert rendered.count(sentinel) == 1
    summary = (topic / "SUMMARY.md").read_text(encoding="utf-8")
    assert "## 보존 원문 파트" in summary
    assert "_generated/mindfresh/CONTEXT-001.md" in summary
    assert before == {path.name: path.read_text(encoding="utf-8") for path in topic.glob("*-source.md")}

    second = refresh_vault(
        vault,
        adapter_name="fake",
        preserve_mode="sharded",
        context_shard_max_chars=4_000,
    )
    assert second[0].status == "unchanged"
