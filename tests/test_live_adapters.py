from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from mindfresh import adapters, cli, config
from mindfresh.adapters import SourceDocument, get_adapter


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _json_summary(**overrides: object) -> str:
    payload: dict[str, object] = {
        "freshness_state": "changed",
        "current_conclusion": "Gemma live adapter summary.",
        "changed_recently": ["New source note was incorporated."],
        "stable_facts": ["Raw source notes remain the evidence boundary."],
        "stale_or_conflicting_claims": [],
        "open_questions": ["Check the next model release note manually."],
        "summary_delta": "One new note changed the topic summary.",
        "updated_claims": ["Updated local claim."],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_ollama_adapter_posts_generate_request_with_stream_disabled(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeHTTPResponse({"response": _json_summary()})

    monkeypatch.setattr(adapters.request, "urlopen", fake_urlopen)
    adapter = get_adapter("ollama", model="gemma4:31b")

    result = adapter.summarize(
        topic="research/topic-a",
        sources=[SourceDocument("note.md", "abc", "# Note\nFresh claim.")],
        recent_sources=[SourceDocument("note.md", "abc", "# Note\nFresh claim.")],
        previous_summary=None,
    )

    assert captured["url"] == "http://localhost:11434/api/generate"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "gemma4:31b"
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert result.model_profile == "ollama/gemma4:31b"
    assert result.current_conclusion == "Gemma live adapter summary."


def test_ollama_diagnostics_checks_installed_model(monkeypatch) -> None:
    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        assert req.full_url == "http://localhost:11434/api/tags"
        assert timeout == 1.5
        return _FakeHTTPResponse({"models": [{"name": "gemma4:31b"}]})

    monkeypatch.setattr(adapters.request, "urlopen", fake_urlopen)

    passes, failures = adapters.adapter_diagnostics("ollama", model="gemma4:31b")

    assert any("ollama model is installed" in item for item in passes)
    assert failures == []


def test_mlx_adapter_invokes_generate_command(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout=_json_summary(), stderr="")

    monkeypatch.setenv("MINDFRESH_MLX_COMMAND", "mlx_lm.generate")
    monkeypatch.setattr(adapters.subprocess, "run", fake_run)
    adapter = get_adapter("mlx", model="/models/gemma-4-31b")

    result = adapter.summarize(
        topic="research/topic-a",
        sources=[SourceDocument("note.md", "abc", "# Note\nFresh claim.")],
        recent_sources=[SourceDocument("note.md", "abc", "# Note\nFresh claim.")],
        previous_summary=None,
    )

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:4] == ["mlx_lm.generate", "--model", "/models/gemma-4-31b", "--prompt"]
    assert "--max-tokens" in cmd
    assert "--temp" in cmd
    assert result.model_profile == "mlx//models/gemma-4-31b"
    assert result.updated_claims == ["Updated local claim."]


def test_registered_vault_model_is_used_when_refresh_has_no_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", cfg_path)
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_FILE", cfg_path)

    vault = tmp_path / "vault"
    topic = vault / "research" / "topic-a"
    topic.mkdir(parents=True)
    (topic / "note.md").write_text("# Local Gemma note\n\nFresh claim.", encoding="utf-8")

    runner = CliRunner()
    add = runner.invoke(
        cli.app,
        [
            "vault",
            "add",
            "research",
            str(vault),
            "--adapter",
            "fake",
            "--model",
            "gemma4-31b-local",
        ],
    )
    assert add.exit_code == 0, add.output

    refresh = runner.invoke(cli.app, ["refresh", "research"])
    assert refresh.exit_code == 0, refresh.output

    summary = (topic / "SUMMARY.md").read_text(encoding="utf-8")
    assert "Model/runtime profile: `fake/gemma4-31b-local`" in summary
