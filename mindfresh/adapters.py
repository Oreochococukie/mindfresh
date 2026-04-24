from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence


@dataclass(frozen=True)
class SourceDocument:
    relative_path: str
    sha256: str
    content: str


@dataclass(frozen=True)
class SummaryResult:
    freshness_state: str
    current_conclusion: str
    changed_recently: Sequence[str]
    stable_facts: Sequence[str]
    stale_or_conflicting_claims: Sequence[str]
    open_questions: Sequence[str]
    summary_delta: str
    updated_claims: Sequence[str]
    model_profile: str


class SummarizerAdapter(Protocol):
    name: str
    model_profile: str

    def summarize(
        self,
        *,
        topic: str,
        sources: Sequence[SourceDocument],
        recent_sources: Sequence[SourceDocument],
        previous_summary: Optional[str],
    ) -> SummaryResult:
        """Summarize topic sources into schema-ready deterministic fields."""


class FakeSummarizerAdapter:
    """Deterministic no-model adapter for tests, CI, and local dry runs."""

    name = "fake"
    model_profile = "fake/deterministic-v1"

    def summarize(
        self,
        *,
        topic: str,
        sources: Sequence[SourceDocument],
        recent_sources: Sequence[SourceDocument],
        previous_summary: Optional[str],
    ) -> SummaryResult:
        source_count = len(sources)
        recent_count = len(recent_sources)
        recent = list(recent_sources or sources)
        corpus = "\n".join(src.content.lower() for src in recent)
        previous = (previous_summary or "").lower()

        if "resolve" in corpus and ("conflict" in previous or "stale-risk" in previous):
            freshness_state = "changed"
        elif "conflict" in corpus or "contradict" in corpus:
            freshness_state = "conflicts"
        elif "stale" in corpus or "outdated" in corpus:
            freshness_state = "stale-risk"
        elif previous_summary is None:
            freshness_state = "fresh"
        else:
            freshness_state = "changed"

        headlines = [_headline(src.content, fallback=src.relative_path) for src in sources]
        recent_headlines = [_headline(src.content, fallback=src.relative_path) for src in recent]
        current = (
            f"Topic `{topic}` reflects {source_count} local source note(s). "
            f"Latest deterministic signal: {', '.join(recent_headlines[:3])}."
        )

        changed = [
            (
                f"`{src.relative_path}` introduced or changed local evidence: "
                f"{_headline(src.content, fallback=src.relative_path)}"
            )
            for src in recent
        ]
        stable = [f"Retained local source signal: {headline}" for headline in headlines[:5]]

        stale_conflicts: list[str] = []
        if freshness_state == "conflicts":
            stale_conflicts.append(
                "Recent local notes contain conflict/contradiction markers that require review."
            )
        elif freshness_state == "stale-risk":
            stale_conflicts.append(
                "Recent local notes mark an unresolved stale-risk or outdated claim."
            )

        if freshness_state in {"conflicts", "stale-risk"}:
            questions = [
                "Review the cited local source notes and decide which claim supersedes "
                "the older summary."
            ]
        else:
            questions = [
                "No conflict marker was detected; continue adding dated research "
                "notes as evidence changes."
            ]

        delta = (
            f"Processed {recent_count} recent source note(s) out of "
            f"{source_count} total source note(s)."
        )
        updated_claims = [
            f"{topic}: {_headline(src.content, fallback=src.relative_path)}"
            for src in recent
        ]

        return SummaryResult(
            freshness_state=freshness_state,
            current_conclusion=current,
            changed_recently=changed,
            stable_facts=stable,
            stale_or_conflicting_claims=stale_conflicts,
            open_questions=questions,
            summary_delta=delta,
            updated_claims=updated_claims,
            model_profile=self.model_profile,
        )


def get_adapter(name: str) -> SummarizerAdapter:
    if name == "fake":
        return FakeSummarizerAdapter()
    raise ValueError(f"unsupported adapter for this build: {name}")


def _headline(content: str, *, fallback: str) -> str:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line in {"---", "..."}:
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
        if ":" in line and line.split(":", 1)[0].strip() in {
            "title",
            "summary",
            "claim",
        }:
            value = line.split(":", 1)[1].strip()
            if value:
                return value
        return line[:120]
    return fallback
