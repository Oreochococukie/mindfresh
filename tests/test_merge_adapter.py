from __future__ import annotations

from pathlib import Path

from mindfresh.refresh import refresh_vault


def test_merge_adapter_builds_one_extractive_latest_note_without_llm(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    topic = vault / "research" / "mindfresh"
    topic.mkdir(parents=True)

    older = topic / "2026-04-24-product.md"
    duplicate = topic / "2026-04-25-copy.md"
    newer = topic / "2026-04-26-product.md"
    unique = topic / "2026-04-26-pricing.md"

    older.write_text(
        "\n".join(
            [
                "# 기능",
                "",
                "Gemini API로 짧은 요약을 만든다.",
                "",
                "## 설치",
                "",
                "pip install mindfresh",
                "",
            ]
        ),
        encoding="utf-8",
    )
    duplicate.write_text(
        "\n".join(
            [
                "# 설치",
                "",
                "pip install mindfresh",
                "",
            ]
        ),
        encoding="utf-8",
    )
    newer.write_text(
        "\n".join(
            [
                "# 기능",
                "",
                "요약하지 않고 원본 Markdown을 병합한다.",
                "중복 내용은 하나로 접고 최신 내용은 최신 파일 기준으로 유지한다.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    unique.write_text(
        "\n".join(
            [
                "# 가격",
                "",
                "API를 쓰지 않는 merge 어댑터는 토큰 출력 제한이 없다.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    before = {path.name: path.read_text(encoding="utf-8") for path in topic.glob("*.md")}

    result = refresh_vault(vault, adapter_name="merge")

    assert result[0].status == "refreshed"
    after = {path.name: path.read_text(encoding="utf-8") for path in topic.glob("2026-*.md")}
    assert before == after
    summary = (topic / "SUMMARY.md").read_text(encoding="utf-8")
    changelog = (topic / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "모델/런타임 프로필: `merge/extractive-v1`" in summary
    assert "외부 모델 요약이 아니라 원본 Markdown 섹션을 그대로 보존" in summary
    assert "요약하지 않고 원본 Markdown을 병합한다." in summary
    assert "Gemini API로 짧은 요약을 만든다." not in summary
    assert summary.count("pip install mindfresh") == 1
    assert "API를 쓰지 않는 merge 어댑터는 토큰 출력 제한이 없다." in summary
    assert "이전 버전은 접었습니다" in summary
    assert "중복/동일 제목 갱신 후보 2개" in changelog


def test_merge_adapter_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    topic = vault / "notes"
    topic.mkdir(parents=True)
    (topic / "2026-04-26-note.md").write_text("# 노트\n\n그대로 보존할 내용.", encoding="utf-8")

    first = refresh_vault(vault, adapter_name="merge")
    second = refresh_vault(vault, adapter_name="merge")

    assert first[0].status == "refreshed"
    assert second[0].status == "unchanged"
    assert second[0].trigger_files == []
