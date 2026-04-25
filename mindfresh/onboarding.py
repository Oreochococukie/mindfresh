from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
import json
import os
import re
import tempfile

ONBOARDING_SCHEMA_VERSION = 1
ONBOARDING_STATE_FILENAME = "onboarding-state.json"


class OnboardingStep(str, Enum):
    """Durable, non-secret checkpoints for guided onboarding."""

    START = "start"
    VAULT = "vault"
    MODEL = "model"
    API_KEYS = "api_keys"
    DOCTOR = "doctor"
    COMPLETE = "complete"


ONBOARDING_STEPS: Sequence[OnboardingStep] = (
    OnboardingStep.START,
    OnboardingStep.VAULT,
    OnboardingStep.MODEL,
    OnboardingStep.API_KEYS,
    OnboardingStep.DOCTOR,
    OnboardingStep.COMPLETE,
)

_SECRET_FIELD_PATTERN = re.compile(r"(api[_-]?key|token|secret|password|credential)", re.IGNORECASE)
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|credential)(\s*[:=]\s*)([^\s,;]+)"
)


@dataclass(frozen=True)
class OnboardingFailure:
    """Last non-secret onboarding failure that can be shown on resume."""

    step: OnboardingStep
    code: str
    message: str

    def to_json(self) -> Dict[str, str]:
        return {
            "step": self.step.value,
            "code": self.code,
            "message": redact_secret_values(self.message),
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "OnboardingFailure":
        return cls(
            step=parse_onboarding_step(str(raw.get("step", OnboardingStep.START.value))),
            code=str(raw.get("code", "unknown")),
            message=redact_secret_values(str(raw.get("message", ""))),
        )


@dataclass(frozen=True)
class OnboardingState:
    """Persisted onboarding progress.

    This intentionally stores only workflow state and human-readable failure
    context. API keys, tokens, credentials, and arbitrary caller metadata are
    never part of the schema.
    """

    current_step: OnboardingStep = OnboardingStep.START
    completed_steps: List[OnboardingStep] = field(default_factory=list)
    last_failure: Optional[OnboardingFailure] = None
    schema_version: int = ONBOARDING_SCHEMA_VERSION

    @property
    def is_complete(self) -> bool:
        return (
            self.current_step == OnboardingStep.COMPLETE
            or OnboardingStep.COMPLETE in self.completed_steps
        )

    def has_completed(self, step: OnboardingStep) -> bool:
        return step in self.completed_steps or self.is_complete

    def to_json(self) -> Dict[str, Any]:
        completed = [step.value for step in _dedupe_steps(self.completed_steps)]
        payload: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "current_step": self.current_step.value,
            "completed_steps": completed,
        }
        if self.last_failure is not None:
            payload["last_failure"] = self.last_failure.to_json()
        return payload

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "OnboardingState":
        completed_raw = raw.get("completed_steps", [])
        completed_steps = _parse_completed_steps(completed_raw)
        failure_raw = raw.get("last_failure")
        last_failure = (
            OnboardingFailure.from_json(failure_raw) if isinstance(failure_raw, Mapping) else None
        )
        version = raw.get("schema_version", ONBOARDING_SCHEMA_VERSION)
        return cls(
            current_step=parse_onboarding_step(
                str(raw.get("current_step", OnboardingStep.START.value))
            ),
            completed_steps=completed_steps,
            last_failure=last_failure,
            schema_version=version if isinstance(version, int) else ONBOARDING_SCHEMA_VERSION,
        )


def onboarding_state_path(config_dir: Path) -> Path:
    """Return the caller-scoped onboarding state file path."""
    return config_dir.expanduser() / ONBOARDING_STATE_FILENAME


def load_onboarding_state(config_dir: Path) -> OnboardingState:
    """Load progress from the caller-provided config dir, or return a fresh state."""
    path = onboarding_state_path(config_dir)
    if not path.exists():
        return OnboardingState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return OnboardingState()
    if not isinstance(raw, Mapping):
        return OnboardingState()
    return OnboardingState.from_json(raw)


def save_onboarding_state(config_dir: Path, state: OnboardingState) -> Path:
    """Atomically write non-secret onboarding state below the given config dir."""
    path = onboarding_state_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_json(), indent=2, sort_keys=True) + "\n"

    tmp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=path.parent,
            delete=False,
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as fp:
            fp.write(payload)
            fp.flush()
            os.fsync(fp.fileno())
            tmp_name = fp.name
        os.replace(tmp_name, path)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return path


def resume_onboarding(config_dir: Path) -> OnboardingState:
    """Return the saved state that a caller can use to resume onboarding."""
    return load_onboarding_state(config_dir)


def restart_onboarding(config_dir: Path) -> OnboardingState:
    """Discard saved progress and return a fresh start state."""
    clear_onboarding_state(config_dir)
    state = OnboardingState()
    save_onboarding_state(config_dir, state)
    return state


def clear_onboarding_state(config_dir: Path) -> None:
    """Remove saved onboarding progress if it exists."""
    try:
        onboarding_state_path(config_dir).unlink()
    except FileNotFoundError:
        return


def mark_step_completed(
    config_dir: Path,
    step: OnboardingStep,
    *,
    next_step: Optional[OnboardingStep] = None,
) -> OnboardingState:
    """Persist a completed step and advance to the next checkpoint."""
    state = load_onboarding_state(config_dir)
    completed = _dedupe_steps([*state.completed_steps, step])
    advanced_step = next_step or _next_step(step)
    if advanced_step == OnboardingStep.COMPLETE and OnboardingStep.COMPLETE not in completed:
        completed.append(OnboardingStep.COMPLETE)
    updated = OnboardingState(
        current_step=advanced_step,
        completed_steps=completed,
        last_failure=None,
        schema_version=state.schema_version,
    )
    save_onboarding_state(config_dir, updated)
    return updated


def record_onboarding_failure(
    config_dir: Path,
    *,
    step: OnboardingStep,
    code: str,
    message: str,
) -> OnboardingState:
    """Persist the last failure and keep onboarding resumable from that step."""
    state = load_onboarding_state(config_dir)
    updated = OnboardingState(
        current_step=step,
        completed_steps=_dedupe_steps(state.completed_steps),
        last_failure=OnboardingFailure(
            step=step,
            code=code,
            message=redact_secret_values(message),
        ),
        schema_version=state.schema_version,
    )
    save_onboarding_state(config_dir, updated)
    return updated


def is_step_completed(config_dir: Path, step: OnboardingStep) -> bool:
    """Return whether a saved state has completed the requested step."""
    return load_onboarding_state(config_dir).has_completed(step)


def parse_onboarding_step(value: str) -> OnboardingStep:
    for step in ONBOARDING_STEPS:
        if step.value == value:
            return step
    return OnboardingStep.START


def redact_secret_values(text: str) -> str:
    """Best-effort redaction for accidental secret-bearing failure messages."""
    redacted = _SECRET_VALUE_PATTERN.sub(r"\1\2[redacted]", text)
    for secret in _known_secret_values():
        redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _parse_completed_steps(raw: Any) -> List[OnboardingStep]:
    if not isinstance(raw, list):
        return []
    parsed: List[OnboardingStep] = []
    for item in raw:
        if isinstance(item, str):
            parsed.append(parse_onboarding_step(item))
    return _dedupe_steps(parsed)


def _dedupe_steps(steps: Iterable[OnboardingStep]) -> List[OnboardingStep]:
    seen: set[OnboardingStep] = set()
    ordered: List[OnboardingStep] = []
    for step in steps:
        if step not in seen:
            seen.add(step)
            ordered.append(step)
    return ordered


def _next_step(step: OnboardingStep) -> OnboardingStep:
    try:
        index = list(ONBOARDING_STEPS).index(step)
    except ValueError:
        return OnboardingStep.START
    if index + 1 >= len(ONBOARDING_STEPS):
        return OnboardingStep.COMPLETE
    return ONBOARDING_STEPS[index + 1]


def _known_secret_values() -> List[str]:
    values: List[str] = []
    for key, value in os.environ.items():
        if value and len(value) >= 8 and _SECRET_FIELD_PATTERN.search(key):
            values.append(value)
    return values
