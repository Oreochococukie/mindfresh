from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mindfresh.onboarding import (
    OnboardingStep,
    clear_onboarding_state,
    is_step_completed,
    load_onboarding_state,
    mark_step_completed,
    onboarding_state_path,
    record_onboarding_failure,
    restart_onboarding,
    resume_onboarding,
)


def test_invalid_api_key_failure_is_resumable_without_storing_secret(
    tmp_path: Path, monkeypatch: Any
) -> None:
    config_dir = tmp_path / "config"
    secret = "MF_SENTINEL_API_KEY_SHOULD_NOT_PERSIST_123"
    monkeypatch.setenv("GOOGLE_API_KEY", secret)

    failed = record_onboarding_failure(
        config_dir,
        step=OnboardingStep.API_KEYS,
        code="invalid_api_key",
        message=f"google api_key={secret} was rejected",
    )

    assert failed.current_step == OnboardingStep.API_KEYS
    assert failed.last_failure is not None
    assert failed.last_failure.code == "invalid_api_key"
    assert secret not in failed.last_failure.message

    saved_text = onboarding_state_path(config_dir).read_text(encoding="utf-8")
    saved_payload = json.loads(saved_text)
    assert saved_payload["current_step"] == "api_keys"
    assert saved_payload["last_failure"]["code"] == "invalid_api_key"
    assert secret not in saved_text
    assert "[redacted]" in saved_text

    resumed = resume_onboarding(config_dir)
    assert resumed.current_step == OnboardingStep.API_KEYS
    assert resumed.last_failure is not None
    assert resumed.last_failure.message == "google api_key=[redacted] was rejected"


def test_completed_checks_and_restart_clear_state(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"

    mark_step_completed(config_dir, OnboardingStep.START)
    mark_step_completed(config_dir, OnboardingStep.VAULT, next_step=OnboardingStep.MODEL)

    assert is_step_completed(config_dir, OnboardingStep.START)
    assert is_step_completed(config_dir, OnboardingStep.VAULT)
    assert not is_step_completed(config_dir, OnboardingStep.API_KEYS)
    assert load_onboarding_state(config_dir).current_step == OnboardingStep.MODEL

    restarted = restart_onboarding(config_dir)
    assert restarted.current_step == OnboardingStep.START
    assert restarted.completed_steps == []
    assert restarted.last_failure is None
    assert onboarding_state_path(config_dir).exists()

    clear_onboarding_state(config_dir)
    assert not onboarding_state_path(config_dir).exists()
    assert load_onboarding_state(config_dir).current_step == OnboardingStep.START
