from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class ModelPreset:
    name: str
    adapter: str
    model: Optional[str]
    description: str


DEFAULT_MODEL_PRESET = "gemini-3-flash"
DEFAULT_GOOGLE_MODEL = "gemini-3-flash-preview"
DEFAULT_GOOGLE_ADAPTER = "google"


MODEL_PRESETS: Dict[str, ModelPreset] = {
    DEFAULT_MODEL_PRESET: ModelPreset(
        name=DEFAULT_MODEL_PRESET,
        adapter=DEFAULT_GOOGLE_ADAPTER,
        model=DEFAULT_GOOGLE_MODEL,
        description="기본값. Google Gemini API의 Gemini 3 Flash preview.",
    ),
    "gemma4-31b-ollama": ModelPreset(
        name="gemma4-31b-ollama",
        adapter="ollama",
        model="gemma4:31b",
        description="로컬 Ollama Gemma 4 31B. 품질 우선, 메모리 요구량 큼.",
    ),
    "qwen3-14b-ollama": ModelPreset(
        name="qwen3-14b-ollama",
        adapter="ollama",
        model="qwen3:14b",
        description="로컬 Ollama Qwen 3 14B. 다른 PC에서 더 가볍게 돌릴 때 사용.",
    ),
    "gemma3-12b-ollama": ModelPreset(
        name="gemma3-12b-ollama",
        adapter="ollama",
        model="gemma3:12b",
        description="로컬 Ollama Gemma 3 12B. 더 작은 로컬 모델 선택지.",
    ),
    "fake": ModelPreset(
        name="fake",
        adapter="fake",
        model=None,
        description="테스트/CI용 결정적 어댑터. 실제 LLM 호출 없음.",
    ),
}


def list_model_presets() -> Iterable[ModelPreset]:
    return [MODEL_PRESETS[name] for name in sorted(MODEL_PRESETS)]


def get_model_preset(name: str) -> ModelPreset:
    try:
        return MODEL_PRESETS[name]
    except KeyError as exc:
        available = ", ".join(sorted(MODEL_PRESETS))
        raise ValueError(f"unknown model preset: {name}; available: {available}") from exc
