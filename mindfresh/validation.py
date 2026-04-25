from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import re
from typing import Iterator, Literal, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .adapters import (
    GOOGLE_API_KEY_ENV_VARS,
    OLLAMA_HOST_ENV_VAR,
    AdapterRuntimeError,
    adapter_diagnostics,
    list_google_generate_models,
)

ValidationStatus = Literal["PASS", "INVALID"]


@dataclass(frozen=True)
class RuntimeValidationResult:
    """Structured, non-secret result for runtime usability checks."""

    status: ValidationStatus
    provider: str
    message: str
    details: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def validate_google_api_key(
    *,
    api_key: Optional[str] = None,
    host: Optional[str] = None,
    timeout_s: float = 30.0,
) -> RuntimeValidationResult:
    """Validate that a Google/Gemini API key can list generateContent models."""

    secrets = _secret_values(api_key)
    try:
        models = list_google_generate_models(api_key=api_key, host=host, timeout_s=timeout_s)
    except AdapterRuntimeError as exc:
        return RuntimeValidationResult(
            status="INVALID",
            provider="google",
            message=_redact_text(str(exc), secrets),
        )

    if not models:
        return RuntimeValidationResult(
            status="INVALID",
            provider="google",
            message="google API key is usable, but no generateContent models were returned",
        )

    return RuntimeValidationResult(
        status="PASS",
        provider="google",
        message="google API key can list generateContent models",
        details=(f"generateContent models available: {len(models)}",),
    )


def validate_ollama_runtime(
    *,
    model: str,
    host: Optional[str] = None,
) -> RuntimeValidationResult:
    """Validate Ollama host reachability and model availability via adapter diagnostics."""

    stripped_model = model.strip()
    secrets = _secret_values(host, *_host_secret_values(host))
    if not stripped_model:
        return RuntimeValidationResult(
            status="INVALID",
            provider="ollama",
            message="ollama model is required",
        )

    with _temporary_env(OLLAMA_HOST_ENV_VAR, host.strip() if host and host.strip() else None):
        passes, failures = adapter_diagnostics("ollama", model=stripped_model)

    sanitized_passes = tuple(_redact_text(item, secrets) for item in passes)
    sanitized_failures = tuple(_redact_text(item, secrets) for item in failures)
    details = sanitized_passes + sanitized_failures

    if failures:
        return RuntimeValidationResult(
            status="INVALID",
            provider="ollama",
            message=sanitized_failures[0],
            details=details,
        )

    return RuntimeValidationResult(
        status="PASS",
        provider="ollama",
        message="ollama runtime can reach the configured host and model",
        details=details,
    )


@contextmanager
def _temporary_env(name: str, value: Optional[str]) -> Iterator[None]:
    if value is None:
        yield
        return

    sentinel = object()
    previous = os.environ.get(name, sentinel)
    try:
        os.environ[name] = value
        yield
    finally:
        if previous is sentinel:
            os.environ.pop(name, None)
        else:
            os.environ[name] = str(previous)


def _secret_values(*additional_values: Optional[str]) -> Tuple[str, ...]:
    values = [value.strip() for value in additional_values if value and value.strip()]
    for name in GOOGLE_API_KEY_ENV_VARS:
        value = os.environ.get(name)
        if value and value.strip():
            values.append(value.strip())
    return tuple(dict.fromkeys(values))


def _host_secret_values(host: Optional[str]) -> Tuple[str, ...]:
    if not host:
        return ()
    parsed = urlsplit(host)
    values = []
    if parsed.password:
        values.append(parsed.password)
    if parsed.username and parsed.password:
        values.append(f"{parsed.username}:{parsed.password}")
    return tuple(values)


def _redact_text(text: str, secrets: Sequence[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(
        r"(?i)([?&](?:key|api_key|apikey|token|password)=)[^&\s]+",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(r"://([^/@\s:]+):([^/@\s]+)@", r"://\1:[REDACTED]@", redacted)
    return redacted
