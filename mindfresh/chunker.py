from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class MarkdownChunk:
    """A deterministic, heading-aware slice of one Markdown source file."""

    source_path: str
    heading_path: Tuple[str, ...]
    ordinal: int
    content: str
    sha256: str
    char_count: int


@dataclass(frozen=True)
class ContextPart:
    """An ordered shard of rendered Markdown chunks constrained by a char budget."""

    ordinal: int
    chunks: Tuple[MarkdownChunk, ...]
    content: str
    sha256: str
    char_count: int


def chunk_markdown_file(path: Path, *, vault_root: Optional[Path] = None) -> List[MarkdownChunk]:
    """Split a Markdown file into ordered chunks at ATX headings.

    Heading paths are derived from the active Markdown heading stack, so a chunk
    under ``# A`` then ``## B`` receives ``("A", "B")``. Headings inside fenced
    code blocks are treated as content, not structure.
    """

    source = Path(path)
    text = source.read_text(encoding="utf-8")
    source_key = _source_key(source, vault_root=vault_root)
    sections = _split_heading_sections(text)
    return [
        _make_chunk(
            source_path=source_key,
            heading_path=heading_path,
            ordinal=index,
            content=content,
        )
        for index, (heading_path, content) in enumerate(sections)
        if content
    ]


def chunk_markdown_files(
    paths: Iterable[Path], *, vault_root: Optional[Path] = None
) -> List[MarkdownChunk]:
    """Chunk Markdown files in deterministic path order."""

    chunks: List[MarkdownChunk] = []
    for path in sorted((Path(item) for item in paths), key=_path_sort_key):
        chunks.extend(chunk_markdown_file(path, vault_root=vault_root))
    return chunks


def shard_chunks(chunks: Sequence[MarkdownChunk], *, max_chars: int) -> List[ContextPart]:
    """Pack chunks into ordered context parts that do not exceed ``max_chars``.

    The rendered chunk envelopes include source metadata and content so each
    shard can be sent independently while preserving provenance. Chunk order is
    never changed. A single chunk larger than the budget is rejected rather than
    silently split inside a heading section.
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")

    parts: List[ContextPart] = []
    current_chunks: List[MarkdownChunk] = []
    current_rendered: List[str] = []
    current_size = 0

    for chunk in chunks:
        rendered = render_chunk(chunk)
        rendered_size = len(rendered)
        if rendered_size > max_chars:
            raise ValueError(
                f"chunk {chunk.source_path}#{chunk.ordinal} exceeds max_chars "
                f"({rendered_size} > {max_chars})"
            )
        separator_size = 2 if current_rendered else 0
        would_size = current_size + separator_size + rendered_size

        if current_rendered and would_size > max_chars:
            parts.append(_make_part(len(parts), current_chunks, current_rendered))
            current_chunks = []
            current_rendered = []
            current_size = 0
            separator_size = 0

        current_chunks.append(chunk)
        current_rendered.append(rendered)
        current_size += separator_size + rendered_size

    if current_rendered:
        parts.append(_make_part(len(parts), current_chunks, current_rendered))

    return parts


def render_chunk(chunk: MarkdownChunk) -> str:
    """Render one chunk with stable metadata for model context preservation."""

    heading = " > ".join(chunk.heading_path) if chunk.heading_path else "(document preamble)"
    return "\n".join(
        [
            f"<!-- mindfresh-chunk {chunk.ordinal} -->",
            f"Source: {chunk.source_path}",
            f"Heading: {heading}",
            f"SHA-256: {chunk.sha256}",
            f"Chars: {chunk.char_count}",
            "",
            chunk.content,
        ]
    )


def _make_chunk(
    *, source_path: str, heading_path: Tuple[str, ...], ordinal: int, content: str
) -> MarkdownChunk:
    return MarkdownChunk(
        source_path=source_path,
        heading_path=heading_path,
        ordinal=ordinal,
        content=content,
        sha256=_sha256_text(content),
        char_count=len(content),
    )


def _make_part(
    ordinal: int, chunks: Sequence[MarkdownChunk], rendered_chunks: Sequence[str]
) -> ContextPart:
    content = "\n\n".join(rendered_chunks)
    return ContextPart(
        ordinal=ordinal,
        chunks=tuple(chunks),
        content=content,
        sha256=_sha256_text(content),
        char_count=len(content),
    )


def _split_heading_sections(markdown: str) -> List[Tuple[Tuple[str, ...], str]]:
    lines = markdown.splitlines(keepends=True)
    sections: List[Tuple[Tuple[str, ...], str]] = []
    active_headings: List[str] = []
    current_heading_path: Tuple[str, ...] = ()
    current_lines: List[str] = []
    in_fence = False
    fence_marker = ""

    for line in lines:
        fence = _fence_marker(line)
        if fence is not None and (not in_fence or fence.startswith(fence_marker)):
            if not in_fence:
                in_fence = True
                fence_marker = fence[:3]
            else:
                in_fence = False
                fence_marker = ""
            current_lines.append(line)
            continue

        heading = None if in_fence else _atx_heading(line)
        if heading is not None:
            if current_lines:
                sections.append((current_heading_path, "".join(current_lines).strip()))
                current_lines = []
            level, title = heading
            active_headings = active_headings[: level - 1]
            active_headings.append(title)
            current_heading_path = tuple(active_headings)

        current_lines.append(line)

    if current_lines:
        sections.append((current_heading_path, "".join(current_lines).strip()))

    return sections


def _atx_heading(line: str) -> Optional[Tuple[int, str]]:
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return None

    marker = stripped.split(maxsplit=1)[0]
    if not 1 <= len(marker) <= 6 or set(marker) != {"#"}:
        return None
    if len(stripped) > len(marker) and not stripped[len(marker)].isspace():
        return None

    title = stripped[len(marker) :].strip()
    while title.endswith("#"):
        title = title[:-1].rstrip()
    if not title:
        return None
    return len(marker), title


def _fence_marker(line: str) -> Optional[str]:
    stripped = line.lstrip()
    if stripped.startswith("```"):
        return stripped
    if stripped.startswith("~~~"):
        return stripped
    return None


def _source_key(path: Path, *, vault_root: Optional[Path]) -> str:
    resolved = path.expanduser().resolve()
    if vault_root is None:
        return resolved.as_posix()
    root = Path(vault_root).expanduser().resolve()
    return resolved.relative_to(root).as_posix()


def _path_sort_key(path: Path) -> str:
    return path.as_posix()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
