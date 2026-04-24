from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shlex
import shutil
import subprocess
import importlib.util
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence
from urllib import error, request

OLLAMA_HOST_ENV_VAR = "MINDFRESH_OLLAMA_HOST"
MLX_COMMAND_ENV_VAR = "MINDFRESH_MLX_COMMAND"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MAX_TOKENS = 1200
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TIMEOUT_S = 600.0
MAX_SOURCE_CHARS = 6000


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


class AdapterRuntimeError(RuntimeError):
    """Raised when an optional live adapter cannot call its local runtime."""


class FakeSummarizerAdapter:
    """Deterministic no-model adapter for tests, CI, and local dry runs."""

    name = "fake"

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model
        self.model_profile = f"fake/{model or 'deterministic-v1'}"

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


class LiveLLMSummarizerAdapter:
    """Base adapter that asks a local LLM for JSON and normalizes fallbacks."""

    name: str

    def __init__(
        self,
        *,
        model: str,
        runtime_label: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if not model:
            raise ValueError(f"{runtime_label} adapter requires --model or a vault model")
        self.model = model
        self.model_profile = f"{runtime_label}/{model}"
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout_s = timeout_s

    def summarize(
        self,
        *,
        topic: str,
        sources: Sequence[SourceDocument],
        recent_sources: Sequence[SourceDocument],
        previous_summary: Optional[str],
    ) -> SummaryResult:
        prompt = _build_live_prompt(
            topic=topic,
            sources=sources,
            recent_sources=recent_sources,
            previous_summary=previous_summary,
        )
        raw = self._generate_text(prompt)
        return _parse_summary_result(raw, model_profile=self.model_profile)

    def _generate_text(self, prompt: str) -> str:
        raise NotImplementedError


class OllamaSummarizerAdapter(LiveLLMSummarizerAdapter):
    """Local Ollama adapter using the documented /api/generate endpoint."""

    name = "ollama"

    def __init__(self, *, model: str, host: Optional[str] = None) -> None:
        super().__init__(model=model, runtime_label=self.name)
        self.host = (host or os.environ.get(OLLAMA_HOST_ENV_VAR) or DEFAULT_OLLAMA_HOST).rstrip("/")

    def _generate_text(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise AdapterRuntimeError(
                f"ollama runtime unavailable at {self.host}; "
                f"start Ollama or set {OLLAMA_HOST_ENV_VAR}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise AdapterRuntimeError("ollama returned non-JSON response") from exc

        generated = response_payload.get("response")
        if not isinstance(generated, str) or not generated.strip():
            raise AdapterRuntimeError("ollama response did not include generated text")
        return generated


class MlxSummarizerAdapter(LiveLLMSummarizerAdapter):
    """Local MLX-LM adapter using the optional mlx_lm.generate CLI."""

    name = "mlx"

    def __init__(self, *, model: str, command: Optional[str] = None) -> None:
        super().__init__(model=model, runtime_label=self.name)
        self.command = _resolve_mlx_command(command)

    def _generate_text(self, prompt: str) -> str:
        cmd = [
            *self.command,
            "--model",
            self.model,
            "--prompt",
            prompt,
            "--max-tokens",
            str(self.max_tokens),
            "--temp",
            str(self.temperature),
        ]
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                text=True,
                capture_output=True,
                timeout=self.timeout_s,
            )
        except FileNotFoundError as exc:
            raise AdapterRuntimeError(
                f"mlx runtime command not found: {self.command[0]}; "
                f"install mlx-lm or set {MLX_COMMAND_ENV_VAR}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AdapterRuntimeError("mlx generation timed out") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise AdapterRuntimeError(f"mlx generation failed: {detail}")
        if not completed.stdout.strip():
            raise AdapterRuntimeError("mlx generation returned no text")
        return completed.stdout


def get_adapter(name: str, *, model: Optional[str] = None) -> SummarizerAdapter:
    normalized = name.strip().lower()
    if normalized == "fake":
        return FakeSummarizerAdapter(model=model)
    if normalized == "ollama":
        return OllamaSummarizerAdapter(model=model or "")
    if normalized == "mlx":
        return MlxSummarizerAdapter(model=model or "")
    raise ValueError(f"unsupported adapter for this build: {name}")


def adapter_diagnostics(name: str, *, model: Optional[str] = None) -> tuple[List[str], List[str]]:
    """Return human-readable runtime diagnostics for config/doctor output."""
    normalized = name.strip().lower()
    passes: List[str] = []
    failures: List[str] = []
    if normalized == "fake":
        passes.append("fake adapter available")
        return passes, failures

    if normalized in {"ollama", "mlx"} and not model:
        failures.append(f"{normalized} adapter requires a model id/path")
        return passes, failures

    if normalized == "ollama":
        host = (os.environ.get(OLLAMA_HOST_ENV_VAR) or DEFAULT_OLLAMA_HOST).rstrip("/")
        passes.append(f"ollama adapter configured for model: {model}")
        passes.append(f"ollama host: {host}")
        _extend_ollama_model_diagnostics(host, model or "", passes, failures)
        return passes, failures

    if normalized == "mlx":
        command = _resolve_mlx_command(None)
        if shutil.which(command[0]) or _python_module_command_available(command):
            passes.append(f"mlx adapter configured for model: {model}")
            passes.append(f"mlx command: {' '.join(command)}")
        else:
            failures.append(f"mlx command not found: {command[0]}")
        _extend_mlx_model_diagnostics(model or "", passes, failures)
        return passes, failures

    failures.append(f"unsupported adapter: {name}")
    return passes, failures


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


def _resolve_mlx_command(command: Optional[str]) -> List[str]:
    raw = command or os.environ.get(MLX_COMMAND_ENV_VAR)
    if raw:
        return shlex.split(raw)
    if shutil.which("mlx_lm.generate"):
        return ["mlx_lm.generate"]
    return ["python3", "-m", "mlx_lm.generate"]


def _python_module_command_available(command: Sequence[str]) -> bool:
    if len(command) < 3 or command[1] != "-m":
        return False
    if shutil.which(command[0]) is None:
        return False
    return importlib.util.find_spec(command[2]) is not None


def _extend_mlx_model_diagnostics(model: str, passes: List[str], failures: List[str]) -> None:
    if _looks_like_local_path(model):
        path = os.path.expanduser(model)
        if os.path.exists(path):
            passes.append(f"mlx model path exists: {path}")
        else:
            failures.append(f"mlx model path does not exist: {path}")
    else:
        passes.append(f"mlx model id will be resolved by mlx-lm: {model}")


def _extend_ollama_model_diagnostics(
    host: str,
    model: str,
    passes: List[str],
    failures: List[str],
) -> None:
    req = request.Request(f"{host}/api/tags", method="GET")
    try:
        with request.urlopen(req, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.URLError:
        failures.append("ollama host is not reachable for /api/tags")
        return
    except json.JSONDecodeError:
        failures.append("ollama /api/tags returned non-JSON response")
        return

    models = payload.get("models")
    names = {
        item.get("model") or item.get("name")
        for item in models
        if isinstance(item, dict)
    } if isinstance(models, list) else set()
    if model in names:
        passes.append(f"ollama model is installed: {model}")
    elif names:
        failures.append(f"ollama model not found in /api/tags: {model}")
    else:
        failures.append("ollama /api/tags returned no installed models")


def _looks_like_local_path(value: str) -> bool:
    return value.startswith(("~", "/", ".")) or os.sep in value


def _build_live_prompt(
    *,
    topic: str,
    sources: Sequence[SourceDocument],
    recent_sources: Sequence[SourceDocument],
    previous_summary: Optional[str],
) -> str:
    recent_paths = {source.relative_path for source in recent_sources}
    source_blocks = "\n\n".join(
        _source_block(source, source.relative_path in recent_paths)
        for source in sources
    )
    previous = (previous_summary or "").strip()
    if len(previous) > MAX_SOURCE_CHARS:
        previous = previous[:MAX_SOURCE_CHARS] + "\n...[truncated]"
    return f"""You are mindfresh, a local-first Markdown research freshness engine.

Task: update a topic-level summary from only the local source notes provided below.

Rules:
- Do not invent facts that are not supported by the source notes.
- Keep stale/conflicting claims explicit.
- Prefer freshness: recent changed notes should drive the delta.
- Return only one valid JSON object. Do not wrap it in Markdown.

Required JSON keys:
- freshness_state: one of "fresh", "changed", "stale-risk", "conflicts"
- current_conclusion: string
- changed_recently: array of strings
- stable_facts: array of strings
- stale_or_conflicting_claims: array of strings
- open_questions: array of strings
- summary_delta: string
- updated_claims: array of strings

Topic: {topic}

Previous generated summary:
{previous or "(none)"}

Local source notes:
{source_blocks}
"""


def _source_block(source: SourceDocument, is_recent: bool) -> str:
    content = source.content
    if len(content) > MAX_SOURCE_CHARS:
        content = content[:MAX_SOURCE_CHARS] + "\n...[truncated]"
    marker = "recent_or_changed" if is_recent else "existing"
    return (
        f"--- SOURCE {source.relative_path} ({marker}, sha256={source.sha256}) ---\n"
        f"{content}"
    )


def _parse_summary_result(raw: str, *, model_profile: str) -> SummaryResult:
    data = _extract_json_object(raw)
    if data is None:
        return _fallback_live_summary(raw, model_profile=model_profile)

    freshness = _coerce_freshness(data.get("freshness_state"))
    return SummaryResult(
        freshness_state=freshness,
        current_conclusion=_coerce_text(
            data.get("current_conclusion"),
            "No conclusion returned.",
        ),
        changed_recently=_coerce_text_list(data.get("changed_recently")),
        stable_facts=_coerce_text_list(data.get("stable_facts")),
        stale_or_conflicting_claims=_coerce_text_list(data.get("stale_or_conflicting_claims")),
        open_questions=_coerce_text_list(data.get("open_questions")),
        summary_delta=_coerce_text(
            data.get("summary_delta"),
            "Live model returned a summary update.",
        ),
        updated_claims=_coerce_text_list(data.get("updated_claims")),
        model_profile=model_profile,
    )


def _extract_json_object(raw: str) -> Optional[Dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _fallback_live_summary(raw: str, *, model_profile: str) -> SummaryResult:
    cleaned = raw.strip() or "The live model returned an empty response."
    return SummaryResult(
        freshness_state="changed",
        current_conclusion=cleaned[:2000],
        changed_recently=[
            "Live model response could not be parsed as JSON; stored raw conclusion."
        ],
        stable_facts=[],
        stale_or_conflicting_claims=[],
        open_questions=[
            "Re-run with a stricter prompt or inspect the cited source notes manually."
        ],
        summary_delta="Live model response was captured through the fallback parser.",
        updated_claims=[],
        model_profile=model_profile,
    )


def _coerce_freshness(value: Any) -> str:
    if isinstance(value, str) and value in {"fresh", "changed", "stale-risk", "conflicts"}:
        return value
    return "changed"


def _coerce_text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is not None:
        return str(value).strip() or fallback
    return fallback


def _coerce_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, Iterable):
        return []
    result: List[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result
