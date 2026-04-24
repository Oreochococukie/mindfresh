from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

PROMPT_SCHEMA_VERSION = "mindfresh-summary-changelog-v1"
SUMMARY_KIND = "summary"
CHANGELOG_KIND = "changelog"

SUMMARY_SECTIONS = (
    "Current conclusion",
    "What changed recently",
    "Stable facts retained",
    "Stale or conflicting claims",
    "Open questions / next checks",
    "Sources considered",
    "Last refreshed metadata",
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
    summary_delta: str
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
        return "- No source files were considered."
    return "\n".join(f"- `{src.path}` — `{src.hash_prefix}`" for src in sources)


def render_summary(
    *,
    topic: str,
    run_id: str,
    timestamp: str,
    result: object,
    source_refs: Sequence[SourceRef],
) -> str:
    """Render SUMMARY.md with required v1 frontmatter and sections.

    The ``result`` object is intentionally structural to keep schema rendering
    decoupled from the concrete adapter implementation.
    """

    body = [
        render_frontmatter(SUMMARY_KIND, topic, run_id),
        "",
        "# SUMMARY",
        "",
        "## Current conclusion",
        str(getattr(result, "current_conclusion")),
        "",
        "## What changed recently",
        _bullet(
            getattr(result, "changed_recently"),
            "No material local source changes were detected for this run.",
        ),
        "",
        "## Stable facts retained",
        _bullet(
            getattr(result, "stable_facts"),
            "No previous stable facts were available to retain.",
        ),
        "",
        "## Stale or conflicting claims",
        _bullet(
            getattr(result, "stale_or_conflicting_claims"),
            "No stale or conflicting local claims were detected.",
        ),
        "",
        "## Open questions / next checks",
        _bullet(
            getattr(result, "open_questions"),
            "No follow-up checks were generated from local inputs.",
        ),
        "",
        "## Sources considered",
        _source_bullets(source_refs),
        "",
        "## Last refreshed metadata",
        f"- Run ID: `{run_id}`",
        f"- Refreshed at: `{timestamp}`",
        f"- Freshness state: `{getattr(result, 'freshness_state')}`",
        f"- Model/runtime profile: `{getattr(result, 'model_profile')}`",
        f"- Prompt schema version: `{PROMPT_SCHEMA_VERSION}`",
        "",
    ]
    return "\n".join(body)


def render_changelog_entry(entry: ChangelogEntry) -> str:
    return "\n".join(
        [
            f"## {entry.timestamp} — run `{entry.run_id}`",
            "",
            f"- Freshness state: `{entry.freshness_state}`",
            f"- Model/runtime profile: `{entry.model_profile}`",
            "- Trigger file(s):",
            _bullet(entry.trigger_files, "No changed source files were identified."),
            "- Summary delta:",
            f"  - {entry.summary_delta}",
            "- Updated claims:",
            _bullet(entry.updated_claims, "No updated claims were produced."),
            "- Stale/conflicting claims:",
            _bullet(
                entry.stale_or_conflicting_claims,
                "No stale or conflicting claims were produced.",
            ),
            "- Source references:",
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

    previous_body = strip_generated_frontmatter(previous or "")
    parts = [
        render_frontmatter(CHANGELOG_KIND, topic),
        "",
        "# CHANGELOG",
        "",
        render_changelog_entry(entry),
    ]
    if previous_body:
        old_without_title = previous_body
        if old_without_title.startswith("# CHANGELOG"):
            old_without_title = old_without_title[len("# CHANGELOG") :].strip()
        if old_without_title:
            parts.extend(["", old_without_title])
    parts.append("")
    return "\n".join(parts)
