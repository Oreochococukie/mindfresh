from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

PROMPT_SCHEMA_VERSION = "mindfresh-refresh-dedupe-v3-ko"
SUMMARY_KIND = "summary"
CHANGELOG_KIND = "changelog"
CONTEXT_KIND = "context"
CHANGELOG_TITLE = "# 최신화·중복제거 변경로그"

SUMMARY_SECTIONS = (
    "최신 기준 정리본",
    "최신화 내역",
    "중복 제거 내역",
    "보존한 원문 맥락",
    "낡았거나 충돌하는 주장",
    "열린 질문 / 다음 확인",
    "검토한 출처",
    "마지막 갱신 메타데이터",
)


@dataclass(frozen=True)
class SourceRef:
    """Rendered source reference for generated Markdown."""

    path: str
    sha256: str

    @property
    def hash_prefix(self) -> str:
        return self.sha256[:12]


@dataclass(frozen=True)
class ChangelogEntry:
    """Structured changelog entry inputs."""

    timestamp: str
    run_id: str
    trigger_files: Sequence[str]
    update_delta: str
    updated_claims: Sequence[str]
    stale_or_conflicting_claims: Sequence[str]
    source_refs: Sequence[SourceRef]
    model_profile: str
    freshness_state: str


def render_frontmatter(kind: str, topic: str, run_id: Optional[str] = None) -> str:
    lines = [
        "---",
        "mindfresh_generated: true",
        f"mindfresh_kind: {kind}",
        f"mindfresh_topic: {topic}",
        f"mindfresh_prompt_schema_version: {PROMPT_SCHEMA_VERSION}",
    ]
    if run_id is not None:
        lines.append(f"mindfresh_run_id: {run_id}")
    lines.append("---")
    return "\n".join(lines)


def _bullet(items: Iterable[str], empty: str) -> str:
    values = [item.strip() for item in items if item and item.strip()]
    if not values:
        return f"- {empty}"
    return "\n".join(f"- {value}" for value in values)


def _source_bullets(sources: Sequence[SourceRef]) -> str:
    if not sources:
        return "- 검토한 원본 파일이 없습니다."
    return "\n".join(f"- `{src.path}` — `{src.hash_prefix}`" for src in sources)


def _freshness_label(value: str) -> str:
    labels = {
        "fresh": "최신",
        "changed": "변경됨",
        "stale-risk": "낡음 위험",
        "conflicts": "충돌 있음",
    }
    return labels.get(value, value)


def render_summary(
    *,
    topic: str,
    run_id: str,
    timestamp: str,
    result: object,
    source_refs: Sequence[SourceRef],
    context_refs: Sequence[str] = (),
) -> str:
    """Render SUMMARY.md as a Korean refresh/dedupe artifact.

    The ``result`` object is intentionally structural to keep schema rendering
    decoupled from the concrete adapter implementation.
    """

    body = [
        render_frontmatter(SUMMARY_KIND, topic, run_id),
        "",
        "# 최신화·중복제거 정리본",
        "",
        *_context_reference_section(context_refs),
        "## 최신 기준 정리본",
        str(getattr(result, "refreshed_context")),
        "",
        "## 최신화 내역",
        _bullet(
            getattr(result, "freshness_updates"),
            "이번 실행에서 중요한 로컬 원본 변경은 감지되지 않았습니다.",
        ),
        "",
        "## 중복 제거 내역",
        _bullet(
            getattr(result, "duplicate_groups"),
            "명시적으로 병합할 중복 주장이 감지되지 않았습니다.",
        ),
        "",
        "## 보존한 원문 맥락",
        _bullet(
            getattr(result, "preserved_context"),
            "추가로 표시할 보존 맥락이 없습니다.",
        ),
        "",
        "## 낡았거나 충돌하는 주장",
        _bullet(
            getattr(result, "stale_or_conflicting_claims"),
            "낡았거나 충돌하는 로컬 주장은 감지되지 않았습니다.",
        ),
        "",
        "## 열린 질문 / 다음 확인",
        _bullet(
            getattr(result, "open_questions"),
            "로컬 입력에서 추가 확인 항목이 생성되지 않았습니다.",
        ),
        "",
        "## 검토한 출처",
        _source_bullets(source_refs),
        "",
        "## 마지막 갱신 메타데이터",
        f"- 실행 ID: `{run_id}`",
        f"- 갱신 시각: `{timestamp}`",
        f"- 신선도 상태: `{_freshness_label(getattr(result, 'freshness_state'))}`",
        f"- 모델/런타임 프로필: `{getattr(result, 'model_profile')}`",
        f"- 프롬프트 스키마 버전: `{PROMPT_SCHEMA_VERSION}`",
        "- 처리 방식: `요약 아님; 최신화와 중복 제거 중심`",
        "",
    ]
    return "\n".join(body)


def render_context_shard(
    *,
    topic: str,
    run_id: Optional[str],
    timestamp: str,
    part: object,
    part_count: int,
) -> str:
    """Render one source-context preservation shard.

    Context shards are intentionally not model summaries. They are generated
    sidecars that keep raw Markdown chunks available when a topic folder is too
    large for a single human-readable ``SUMMARY.md``.
    """

    ordinal = int(getattr(part, "ordinal")) + 1
    content = str(getattr(part, "content"))
    char_count = int(getattr(part, "char_count"))
    sha256 = str(getattr(part, "sha256"))
    return "\n".join(
        [
            render_frontmatter(CONTEXT_KIND, topic, run_id),
            "",
            f"# 보존 원문 파트 {ordinal:03d}/{part_count:03d}",
            "",
            "- 이 파일은 요약본이 아니라 원문 맥락 보존용 생성 파일입니다.",
            "- 중복 제거·최신화 판단은 `SUMMARY.md`와 `CHANGELOG.md`를 확인하세요.",
            f"- 갱신 시각: `{timestamp}`",
            f"- 파트 해시: `{sha256[:12]}`",
            f"- 문자 수: `{char_count}`",
            "",
            "## 원문 청크",
            "",
            content,
            "",
        ]
    )


def _context_reference_section(context_refs: Sequence[str]) -> list[str]:
    if not context_refs:
        return []
    return [
        "## 보존 원문 파트",
        "",
        "아래 파일들은 큰 주제 폴더의 비중복 원문 맥락을 요약하지 않고 보존하기 위한 생성 파일입니다.",
        _bullet(context_refs, "생성된 보존 원문 파트가 없습니다."),
        "",
    ]


def render_changelog_entry(entry: ChangelogEntry) -> str:
    return "\n".join(
        [
            f"## {entry.timestamp} — run `{entry.run_id}`",
            "",
            f"- 신선도 상태: `{_freshness_label(entry.freshness_state)}`",
            f"- 모델/런타임 프로필: `{entry.model_profile}`",
            "- 트리거 파일:",
            _bullet(entry.trigger_files, "변경된 원본 파일이 확인되지 않았습니다."),
            "- 정리본 변경점:",
            f"  - {entry.update_delta}",
            "- 업데이트된 주장:",
            _bullet(entry.updated_claims, "업데이트된 주장이 생성되지 않았습니다."),
            "- 낡았거나 충돌하는 주장:",
            _bullet(
                entry.stale_or_conflicting_claims,
                "낡았거나 충돌하는 주장이 생성되지 않았습니다.",
            ),
            "- 출처 참조:",
            _source_bullets(entry.source_refs),
        ]
    )


def strip_generated_frontmatter(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown.strip()
    closing = markdown.find("\n---", 4)
    if closing == -1:
        return markdown.strip()
    return markdown[closing + len("\n---") :].strip()


def render_changelog(*, topic: str, entry: ChangelogEntry, previous: Optional[str] = None) -> str:
    """Render CHANGELOG.md, prepending newest run entries."""

    previous_text = previous or ""
    previous_body = (
        strip_generated_frontmatter(previous_text)
        if f"mindfresh_prompt_schema_version: {PROMPT_SCHEMA_VERSION}" in previous_text
        else ""
    )
    parts = [
        render_frontmatter(CHANGELOG_KIND, topic),
        "",
        CHANGELOG_TITLE,
        "",
        render_changelog_entry(entry),
    ]
    if previous_body:
        old_without_title = previous_body
        for title in (CHANGELOG_TITLE, "# 변경로그", "# CHANGELOG"):
            if old_without_title.startswith(title):
                old_without_title = old_without_title[len(title) :].strip()
                break
        if old_without_title:
            parts.extend(["", old_without_title])
    parts.append("")
    return "\n".join(parts)
