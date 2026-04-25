from __future__ import annotations

import io
import json
from typing import Any

from mindfresh import adapters
from mindfresh.validation import validate_google_api_key, validate_ollama_runtime


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_validate_google_api_key_passes_when_generate_models_are_listed(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["timeout"] = timeout
        return _FakeHTTPResponse(
            {
                "models": [
                    {
                        "name": "models/gemini-3-flash-preview",
                        "displayName": "Gemini 3 Flash Preview",
                        "supportedGenerationMethods": ["generateContent"],
                    }
                ]
            }
        )

    monkeypatch.setattr(adapters.request, "urlopen", fake_urlopen)

    result = validate_google_api_key(api_key="test-google-key", timeout_s=2.0)

    assert result.status == "PASS"
    assert result.ok is True
    assert result.provider == "google"
    assert result.message == "google API key can list generateContent models"
    assert result.details == ("generateContent models available: 1",)
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100"
    assert captured["headers"]["X-goog-api-key"] == "test-google-key"  # type: ignore[index]
    assert captured["timeout"] == 2.0


def test_validate_google_api_key_redacts_secret_from_http_error(monkeypatch) -> None:
    secret = "MF_SENTINEL_GOOGLE_VALIDATION_SECRET"

    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        raise adapters.error.HTTPError(
            req.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(f'{{"error":"bad key {secret}"}}'.encode("utf-8")),
        )

    monkeypatch.setattr(adapters.request, "urlopen", fake_urlopen)

    result = validate_google_api_key(api_key=secret)

    assert result.status == "INVALID"
    assert result.ok is False
    assert "google model listing failed with HTTP 403" in result.message
    assert "[REDACTED]" in result.message
    assert secret not in result.message
    assert result.details == ()


def test_validate_google_api_key_invalid_when_no_generate_models(monkeypatch) -> None:
    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        return _FakeHTTPResponse(
            {
                "models": [
                    {
                        "name": "models/text-embedding-004",
                        "displayName": "Embedding",
                        "supportedGenerationMethods": ["embedContent"],
                    }
                ]
            }
        )

    monkeypatch.setattr(adapters.request, "urlopen", fake_urlopen)

    result = validate_google_api_key(api_key="test-google-key")

    assert result.status == "INVALID"
    assert result.message == "google API key is usable, but no generateContent models were returned"


def test_validate_ollama_runtime_passes_for_installed_model(monkeypatch) -> None:
    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        assert req.full_url == "http://ollama.local:11434/api/tags"
        assert timeout == 1.5
        return _FakeHTTPResponse({"models": [{"name": "gemma4:31b"}]})

    monkeypatch.setattr(adapters.request, "urlopen", fake_urlopen)

    result = validate_ollama_runtime(model="gemma4:31b", host="http://ollama.local:11434")

    assert result.status == "PASS"
    assert result.ok is True
    assert result.provider == "ollama"
    assert result.message == "ollama runtime can reach the configured host and model"
    assert any("ollama model is installed: gemma4:31b" in item for item in result.details)


def test_validate_ollama_runtime_invalid_for_missing_model(monkeypatch) -> None:
    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        return _FakeHTTPResponse({"models": [{"name": "other-model"}]})

    monkeypatch.setattr(adapters.request, "urlopen", fake_urlopen)

    result = validate_ollama_runtime(model="gemma4:31b", host="http://localhost:11434")

    assert result.status == "INVALID"
    assert "ollama model not found in /api/tags: gemma4:31b" in result.message
    assert result.message in result.details


def test_validate_ollama_runtime_redacts_host_password_from_diagnostics(monkeypatch) -> None:
    secret = "ollama-password-secret"

    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        raise adapters.error.URLError("boom")

    monkeypatch.setattr(adapters.request, "urlopen", fake_urlopen)

    result = validate_ollama_runtime(
        model="gemma4:31b",
        host=f"http://user:{secret}@localhost:11434",
    )

    rendered = "\n".join((result.message, *result.details))
    assert result.status == "INVALID"
    assert "[REDACTED]" in rendered
    assert secret not in rendered
