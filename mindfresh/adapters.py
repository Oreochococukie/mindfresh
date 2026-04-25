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
from urllib.parse import quote, urlencode

from .model_presets import DEFAULT_GOOGLE_MODEL

OLLAMA_HOST_ENV_VAR = "MINDFRESH_OLLAMA_HOST"
MLX_COMMAND_ENV_VAR = "MINDFRESH_MLX_COMMAND"
GOOGLE_API_KEY_ENV_VARS = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
GOOGLE_API_HOST_ENV_VAR = "MINDFRESH_GOOGLE_API_HOST"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_GOOGLE_API_HOST = "https://generativelanguage.googleapis.com/v1beta"
MAX_OUTPUT_TOKENS_ENV_VAR = "MINDFRESH_MAX_OUTPUT_TOKENS"
SOURCE_CHAR_LIMIT_ENV_VAR = "MINDFRESH_MAX_SOURCE_CHARS"
DEFAULT_MAX_TOKENS = 16384
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TIMEOUT_S = 600.0
DEFAULT_SOURCE_CHAR_LIMIT = 0
MAX_SOURCE_CHARS = DEFAULT_SOURCE_CHAR_LIMIT


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


@dataclass(frozen=True)
class GoogleModelInfo:
    """Non-secret metadata returned by the Gemini API models.list endpoint."""

    name: str
    display_name: str
    description: str
    input_token_limit: Optional[int]
    output_token_limit: Optional[int]
    supported_generation_methods: Sequence[str]

    @property
    def model_id(self) -> str:
        return self.name.removeprefix("models/")


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


def _non_negative_int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise AdapterRuntimeError(f"{name} must be an integer") from exc
    if value < 0:
        raise AdapterRuntimeError(f"{name} must be greater than or equal to 0")
    return value


def _positive_int_from_env(name: str, default: int) -> int:
    value = _non_negative_int_from_env(name, default)
    if value <= 0:
        raise AdapterRuntimeError(f"{name} must be greater than 0")
    return value


def _default_max_tokens() -> int:
    return _positive_int_from_env(MAX_OUTPUT_TOKENS_ENV_VAR, DEFAULT_MAX_TOKENS)


def _source_char_limit() -> Optional[int]:
    limit = _non_negative_int_from_env(SOURCE_CHAR_LIMIT_ENV_VAR, DEFAULT_SOURCE_CHAR_LIMIT)
    return limit if limit > 0 else None


def _limit_prompt_text(text: str, *, label: str) -> str:
    limit = _source_char_limit()
    if limit is None or len(text) <= limit:
        return text
    return (
        text[:limit]
        + "\n\n"
        + "[입력 길이 제한: "
        + f"{label} 원문이 {limit}자로 잘렸습니다. "
        + f"전체 원문 보존이 필요하면 {SOURCE_CHAR_LIMIT_ENV_VAR}=0 또는 더 큰 값으로 설정하세요.]"
    )


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
        max_tokens: Optional[int] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if not model:
            raise ValueError(f"{runtime_label} adapter requires --model or a vault model")
        self.model = model
        self.model_profile = f"{runtime_label}/{model}"
        self.max_tokens = max_tokens if max_tokens is not None else _default_max_tokens()
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


class GoogleGeminiSummarizerAdapter(LiveLLMSummarizerAdapter):
    """Google Gemini API adapter using the REST generateContent endpoint."""

    name = "google"

    def __init__(
        self,
        *,
        model: str = DEFAULT_GOOGLE_MODEL,
        api_key: Optional[str] = None,
        host: Optional[str] = None,
    ) -> None:
        super().__init__(model=model or DEFAULT_GOOGLE_MODEL, runtime_label=self.name)
        self.api_key = api_key or _google_api_key()
        self.host = (
            host or os.environ.get(GOOGLE_API_HOST_ENV_VAR) or DEFAULT_GOOGLE_API_HOST
        ).rstrip("/")

    def _generate_text(self, prompt: str) -> str:
        if not self.api_key:
            joined = " or ".join(GOOGLE_API_KEY_ENV_VARS)
            raise AdapterRuntimeError(f"google adapter requires {joined}")

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
                "responseMimeType": "application/json",
            },
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            _google_generate_url(self.host, self.model),
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = _redact_secret_values(
                exc.read().decode("utf-8", errors="replace").strip(),
                self.api_key,
            )
            message = f"google generation failed with HTTP {exc.code}"
            raise AdapterRuntimeError(f"{message}: {detail}" if detail else message) from exc
        except error.URLError as exc:
            raise AdapterRuntimeError(
                f"google runtime unavailable at {self.host}; "
                f"check network or {GOOGLE_API_HOST_ENV_VAR}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise AdapterRuntimeError("google returned non-JSON response") from exc

        generated = _extract_google_response_text(response_payload)
        if not generated.strip():
            reason = _google_response_block_reason(response_payload)
            detail = f": {reason}" if reason else ""
            raise AdapterRuntimeError(f"google response did not include generated text{detail}")
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
    if normalized in {"google", "gemini"}:
        return GoogleGeminiSummarizerAdapter(model=model or DEFAULT_GOOGLE_MODEL)
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

    if normalized in {"google", "gemini"}:
        selected_model = model or DEFAULT_GOOGLE_MODEL
        host = (os.environ.get(GOOGLE_API_HOST_ENV_VAR) or DEFAULT_GOOGLE_API_HOST).rstrip("/")
        passes.append(f"google adapter configured for model: {selected_model}")
        passes.append(f"google host: {host}")
        if _google_api_key():
            passes.append(
                "google API key available via "
                + " or ".join(GOOGLE_API_KEY_ENV_VARS)
            )
        else:
            failures.append(
                "google API key missing; set "
                + " or ".join(GOOGLE_API_KEY_ENV_VARS)
            )
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


def _redact_secret_values(text: str, *additional_values: Optional[str]) -> str:
    redacted = text
    secret_values = [
        value.strip()
        for value in (*additional_values, *(os.environ.get(name) for name in GOOGLE_API_KEY_ENV_VARS))
        if value and value.strip()
    ]
    for value in sorted(set(secret_values), key=len, reverse=True):
        redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def _google_api_key() -> Optional[str]:
    for env_var in GOOGLE_API_KEY_ENV_VARS:
        value = os.environ.get(env_var)
        if value and value.strip():
            return value.strip()
    return None


def list_google_models(
    *,
    api_key: Optional[str] = None,
    host: Optional[str] = None,
    page_size: int = 100,
    timeout_s: float = 30.0,
    generation_method: Optional[str] = None,
) -> List[GoogleModelInfo]:
    """List Gemini API models available to the configured API key.

    The API key is sent as a header and is never returned by this function.
    When ``generation_method`` is set, only models advertising that supported
    generation method are returned. For Mindfresh refreshes this is normally
    ``generateContent``.
    """

    key = api_key or _google_api_key()
    if not key:
        joined = " or ".join(GOOGLE_API_KEY_ENV_VARS)
        raise AdapterRuntimeError(f"google adapter requires {joined}")

    selected_host = (host or os.environ.get(GOOGLE_API_HOST_ENV_VAR) or DEFAULT_GOOGLE_API_HOST)
    selected_host = selected_host.rstrip("/")
    page_token: Optional[str] = None
    models: List[GoogleModelInfo] = []

    while True:
        params = {"pageSize": str(page_size)}
        if page_token:
            params["pageToken"] = page_token
        req = request.Request(
            f"{selected_host}/models?{urlencode(params)}",
            headers={"x-goog-api-key": key},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = _redact_secret_values(
                exc.read().decode("utf-8", errors="replace").strip(),
                key,
            )
            message = f"google model listing failed with HTTP {exc.code}"
            raise AdapterRuntimeError(f"{message}: {detail}" if detail else message) from exc
        except error.URLError as exc:
            raise AdapterRuntimeError(
                f"google model listing unavailable at {selected_host}; "
                f"check network or {GOOGLE_API_HOST_ENV_VAR}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise AdapterRuntimeError("google model listing returned non-JSON response") from exc

        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise AdapterRuntimeError("google model listing response did not include models[]")
        for raw_model in raw_models:
            if isinstance(raw_model, dict):
                models.append(_google_model_info_from_mapping(raw_model))

        token = payload.get("nextPageToken")
        if not isinstance(token, str) or not token.strip():
            break
        page_token = token.strip()

    if generation_method is None:
        return models
    return [
        model
        for model in models
        if generation_method in model.supported_generation_methods
    ]


def list_google_generate_models(
    *,
    api_key: Optional[str] = None,
    host: Optional[str] = None,
    page_size: int = 100,
    timeout_s: float = 30.0,
) -> List[GoogleModelInfo]:
    """List Gemini API models that support models.generateContent."""

    return list_google_models(
        api_key=api_key,
        host=host,
        page_size=page_size,
        timeout_s=timeout_s,
        generation_method="generateContent",
    )


def _google_model_info_from_mapping(raw: Dict[str, Any]) -> GoogleModelInfo:
    methods = raw.get("supportedGenerationMethods")
    if not isinstance(methods, list):
        methods = []
    return GoogleModelInfo(
        name=str(raw.get("name") or ""),
        display_name=str(raw.get("displayName") or raw.get("name") or ""),
        description=str(raw.get("description") or ""),
        input_token_limit=_optional_int(raw.get("inputTokenLimit")),
        output_token_limit=_optional_int(raw.get("outputTokenLimit")),
        supported_generation_methods=tuple(item for item in methods if isinstance(item, str)),
    )


def _optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _google_generate_url(host: str, model: str) -> str:
    model_id = model.removeprefix("models/")
    return f"{host}/models/{quote(model_id, safe='-_.:')}:generateContent"


def _extract_google_response_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    texts: List[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return "\n".join(texts)


def _google_response_block_reason(payload: Dict[str, Any]) -> Optional[str]:
    prompt_feedback = payload.get("promptFeedback")
    if isinstance(prompt_feedback, dict):
        block_reason = prompt_feedback.get("blockReason")
        if isinstance(block_reason, str) and block_reason.strip():
            return f"prompt blocked: {block_reason.strip()}"

    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return None

    finish_reasons: List[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        finish_reason = candidate.get("finishReason")
        if not isinstance(finish_reason, str):
            continue
        normalized = finish_reason.strip()
        if normalized and normalized not in {"STOP", "FINISH_REASON_UNSPECIFIED"}:
            finish_reasons.append(normalized)
    if finish_reasons:
        unique = ", ".join(dict.fromkeys(finish_reasons))
        return f"candidate finish reason(s): {unique}"
    return None


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
    previous = _limit_prompt_text((previous_summary or "").strip(), label="이전 생성 정리본")
    return f"""당신은 로컬 우선 Markdown 연구 신선도 엔진 mindfresh입니다.

작업: 아래에 제공된 로컬 원본 노트만 사용해서 주제 단위 정리본을 최신화하고 중복을 제거하세요.
중요: 이것은 요약 작업이 아닙니다. 모든 원본 파일의 원문 맥락을 최대한 유지하면서 중복·충돌·최신화 지점만 정리하세요.

규칙:
- 원본 노트가 뒷받침하지 않는 사실을 만들지 마세요.
- 의미가 같은 중복 주장은 최신/가장 구체적인 표현 하나로 합치고, 합친 출처를 중복 제거 내역에 남기세요.
- 낡았거나 충돌하는 주장은 조용히 지우지 말고 명시적으로 표시하세요.
- 신선도를 우선하세요. 최근 변경 노트가 기존 정리본과 충돌하면 최근 노트가 변경점을 주도해야 합니다.
- 서로 겹치지 않는 섹션, 표, 날짜, 수치, 조건, 예외, 판단 근거, 비교 맥락은 병합하거나 압축하지 말고 원문 구조에 가깝게 유지하세요.
- 원문에만 있는 세부 항목은 "덜 중요해 보인다"는 이유로 제거하지 마세요. 중복이 아닌 맥락은 보존 대상입니다.
- 중복/충돌/최신화가 필요한 부분만 재정리하고, 나머지 비중복 원문 맥락은 가능한 한 상세히 유지하세요.
- 입력에 "[입력 길이 제한:" 표시가 있으면 해당 원본은 불완전하다고 열린 질문 또는 충돌/낡음 항목에 남기세요.
- 사람에게 보이는 모든 값은 반드시 한국어로 작성하세요.
- 영어 섹션명이나 영어 문장으로 답하지 마세요.
- 유효한 JSON 객체 하나만 반환하세요. Markdown 코드블록으로 감싸지 마세요.

필수 JSON key:
- freshness_state: one of "fresh", "changed", "stale-risk", "conflicts"
- refreshed_context: 한국어 Markdown 문자열. 짧은 요약이 아니라 원문 컨텍스트를 거의 보존한 최신 기준 정리본. 비중복 원문 맥락은 상세히 유지.
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
    content = _limit_prompt_text(source.content, label=f"`{source.relative_path}`")
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
        refreshed_context=cleaned,
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
