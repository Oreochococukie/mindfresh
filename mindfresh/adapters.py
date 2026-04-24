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
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TIMEOUT_S = 600.0
MAX_SOURCE_CHARS = 12000


@dataclass(frozen=True)
class SourceDocument:
    relative_path: str
    sha256: str
    content: str


@dataclass(frozen=True)
class SummaryResult:
    freshness_state: str
    refreshed_context: str
    freshness_updates: Sequence[str]
    duplicate_groups: Sequence[str]
    preserved_context: Sequence[str]
    stale_or_conflicting_claims: Sequence[str]
    open_questions: Sequence[str]
    update_delta: str
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
    """Deterministic Korean no-model adapter for tests, CI, and local dry runs."""

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
        refreshed_context = (
            f"`{topic}` 주제는 요약하지 않고 로컬 원본 노트 {source_count}개의 "
            "핵심 맥락을 최신 기준으로 다시 배열한 정리본입니다.\n\n"
            + "\n".join(
                f"- `{src.relative_path}`: {_headline(src.content, fallback=src.relative_path)}"
                for src in sources
            )
        )

        freshness_updates = [
            (
                f"`{src.relative_path}` 파일이 추가 또는 변경한 로컬 근거: "
                f"{_headline(src.content, fallback=src.relative_path)}"
            )
            for src in recent
        ]
        duplicate_groups = _duplicate_headline_groups(sources)
        preserved_context = [
            f"원본 맥락 보존: {headline}"
            for headline in headlines[:5]
        ]

        stale_conflicts: list[str] = []
        if freshness_state == "conflicts":
            stale_conflicts.append(
                "최근 로컬 노트에 검토가 필요한 충돌/모순 표시가 포함되어 있습니다."
            )
        elif freshness_state == "stale-risk":
            stale_conflicts.append(
                "최근 로컬 노트에 해결되지 않은 낡음 위험 또는 오래된 주장이 표시되어 있습니다."
            )

        if freshness_state in {"conflicts", "stale-risk"}:
            questions = [
                "인용된 로컬 원본 노트를 확인하고 어떤 주장이 이전 정리본을 대체하는지 결정하세요."
            ]
        else:
            questions = [
                "충돌 표시는 감지되지 않았습니다. 근거가 바뀔 때 날짜가 있는 연구 노트를 계속 추가하세요."
            ]

        delta = (
            f"요약 생성 없이 전체 원본 노트 {source_count}개 중 최근 원본 노트 "
            f"{recent_count}개를 최신화·중복제거 기준으로 처리했습니다."
        )
        updated_claims = [
            f"{topic}: {_headline(src.content, fallback=src.relative_path)}"
            for src in recent
        ]

        return SummaryResult(
            freshness_state=freshness_state,
            refreshed_context=refreshed_context,
            freshness_updates=freshness_updates,
            duplicate_groups=duplicate_groups,
            preserved_context=preserved_context,
            stale_or_conflicting_claims=stale_conflicts,
            open_questions=questions,
            update_delta=delta,
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


def _duplicate_headline_groups(sources: Sequence[SourceDocument]) -> List[str]:
    """Return deterministic duplicate groups for fake-adapter output."""

    by_headline: Dict[str, List[str]] = {}
    display: Dict[str, str] = {}
    for source in sources:
        headline = _headline(source.content, fallback=source.relative_path)
        key = " ".join(headline.casefold().split())
        by_headline.setdefault(key, []).append(source.relative_path)
        display.setdefault(key, headline)

    groups: List[str] = []
    for key in sorted(by_headline):
        paths = by_headline[key]
        if len(paths) <= 1:
            continue
        groups.append(
            f"`{display[key]}` 주장이 {', '.join(f'`{path}`' for path in paths)}에서 "
            "반복되어 최신 정리본에는 한 번만 유지했습니다."
        )
    return groups


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
    return f"""당신은 로컬 우선 Markdown 연구 신선도 엔진 mindfresh입니다.

작업: 아래에 제공된 로컬 원본 노트만 사용해서 주제 단위 정리본을 최신화하고 중복을 제거하세요.
중요: 이것은 요약 작업이 아닙니다. 원문의 날짜, 수치, 조건, 예외, 판단 근거, 비교 맥락을 가능한 한 보존하세요.

규칙:
- 원본 노트가 뒷받침하지 않는 사실을 만들지 마세요.
- 의미가 같은 중복 주장은 최신/가장 구체적인 표현 하나로 합치고, 합친 출처를 중복 제거 내역에 남기세요.
- 낡았거나 충돌하는 주장은 조용히 지우지 말고 명시적으로 표시하세요.
- 신선도를 우선하세요. 최근 변경 노트가 기존 정리본과 충돌하면 최근 노트가 변경점을 주도해야 합니다.
- 추상적인 한 문단 요약으로 압축하지 마세요. 주제별 하위 항목과 원문 세부 맥락을 유지한 Markdown 정리본을 작성하세요.
- 사람에게 보이는 모든 값은 반드시 한국어로 작성하세요.
- 영어 섹션명이나 영어 문장으로 답하지 마세요.
- 유효한 JSON 객체 하나만 반환하세요. Markdown 코드블록으로 감싸지 마세요.

필수 JSON key:
- freshness_state: one of "fresh", "changed", "stale-risk", "conflicts"
- refreshed_context: 한국어 Markdown 문자열. 짧은 요약이 아니라 중복을 제거한 최신 기준 정리본.
- freshness_updates: 한국어 문자열 배열. 무엇이 최신화되었는지.
- duplicate_groups: 한국어 문자열 배열. 어떤 중복을 하나로 합쳤는지.
- preserved_context: 한국어 문자열 배열. 잘라내지 않고 보존한 중요한 원문 맥락.
- stale_or_conflicting_claims: 한국어 문자열 배열
- open_questions: 한국어 문자열 배열
- update_delta: 한국어 문자열
- updated_claims: 한국어 문자열 배열

주제: {topic}

이전 생성 정리본:
{previous or "(없음)"}

로컬 원본 노트:
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
        refreshed_context=_coerce_text(
            data.get("refreshed_context") or data.get("current_conclusion"),
            "모델이 최신 기준 정리본을 반환하지 않았습니다.",
        ),
        freshness_updates=_coerce_text_list(
            data.get("freshness_updates") or data.get("changed_recently")
        ),
        duplicate_groups=_coerce_text_list(data.get("duplicate_groups")),
        preserved_context=_coerce_text_list(
            data.get("preserved_context") or data.get("stable_facts")
        ),
        stale_or_conflicting_claims=_coerce_text_list(data.get("stale_or_conflicting_claims")),
        open_questions=_coerce_text_list(data.get("open_questions")),
        update_delta=_coerce_text(
            data.get("update_delta") or data.get("summary_delta"),
            "라이브 모델이 최신화·중복제거 갱신을 반환했습니다.",
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
    cleaned = raw.strip() or "라이브 모델이 빈 응답을 반환했습니다."
    return SummaryResult(
        freshness_state="changed",
        refreshed_context=cleaned[:4000],
        freshness_updates=[
            "라이브 모델 응답을 JSON으로 파싱하지 못해 원문 응답을 정리본 영역에 저장했습니다."
        ],
        duplicate_groups=[],
        preserved_context=[],
        stale_or_conflicting_claims=[],
        open_questions=[
            "더 엄격한 프롬프트로 다시 실행하거나 인용된 원본 노트를 직접 확인하세요."
        ],
        update_delta="라이브 모델 응답이 fallback 파서를 통해 기록되었습니다.",
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
