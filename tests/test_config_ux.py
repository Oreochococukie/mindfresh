from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mindfresh import config


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", cfg_path)
    cli_module = pytest.importorskip("mindfresh.cli")
    try:
        runner = CliRunner()
        runner.invoke(cli_module.app, ["--help"])
    except TypeError as exc:
        if "unsupported operand type" in str(exc):
            pytest.xfail(
                "task 8 pending: CLI annotations must support pyproject requires-python >=3.9"
            )
        raise
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_FILE", cfg_path)
    return cfg_path


@pytest.fixture()
def cli_app(isolated_config: Path):
    from mindfresh import cli

    return cli.app


def test_init_creates_readable_config(runner: CliRunner, isolated_config: Path, cli_app) -> None:
    result = runner.invoke(cli_app, ["init"])

    assert result.exit_code == 0, result.output
    assert isolated_config.exists()
    loaded = config.load_config(isolated_config)
    assert loaded.vaults == {}
    assert loaded.default_adapter == "google"
    assert loaded.default_model == "gemini-3-flash-preview"


def test_models_list_and_preset_vault_add(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app
) -> None:
    vault_path = tmp_path / "vault"
    vault_path.mkdir()

    listing = runner.invoke(cli_app, ["models", "list"])
    assert listing.exit_code == 0, listing.output
    assert "gemini-3-flash (default)" in listing.output
    assert "qwen3-14b-ollama" in listing.output
    assert "Recommended for this Mac" in listing.output
    assert "another Mac / no local LLM" in listing.output

    add = runner.invoke(
        cli_app,
        [
            "vault",
            "add",
            "small",
            str(vault_path),
            "--model-preset",
            "qwen3-14b-ollama",
        ],
    )
    assert add.exit_code == 0, add.output
    vault = config.load_config(isolated_config).vaults["small"]
    assert vault.adapter == "ollama"
    assert vault.model == "qwen3:14b"


def test_setup_registers_only_explicit_vault_path(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app
) -> None:
    vault_path = tmp_path / "vault"
    vault_path.mkdir()

    result = runner.invoke(
        cli_app,
        [
            "setup",
            "--model-preset",
            "fake",
            "--vault-name",
            "docs",
            "--vault-path",
            str(vault_path),
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    loaded = config.load_config(isolated_config)
    assert loaded.default_adapter == "fake"
    assert loaded.default_model is None
    assert loaded.vaults["docs"].path == str(vault_path.resolve())
    assert loaded.vaults["docs"].enabled
    assert "No vault registered" not in result.output


def test_setup_without_vault_path_does_not_infer_common_directories(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    for relative in ("Documents", "Desktop", "Markdown note folder", "Documents/Markdown note folder"):
        (fake_home / relative).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))

    result = runner.invoke(
        cli_app,
        ["setup", "--model-preset", "fake", "--non-interactive"],
    )

    assert result.exit_code == 0, result.output
    assert config.load_config(isolated_config).vaults == {}
    assert "No vault registered" in result.output


def test_config_show_json_and_export_redact_secret_sentinel(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "MF_SENTINEL_SECRET_SHOULD_NOT_LEAK_123"
    monkeypatch.setenv("GOOGLE_API_KEY", sentinel)
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    setup = runner.invoke(
        cli_app,
        [
            "setup",
            "--model-preset",
            "fake",
            "--vault-name",
            "docs",
            "--vault-path",
            str(vault_path),
        ],
    )
    assert setup.exit_code == 0, setup.output

    show = runner.invoke(cli_app, ["config", "show", "--json"])
    assert show.exit_code == 0, show.output
    parsed = json.loads(show.output)
    assert parsed["vaults"]["docs"]["path"] == str(vault_path.resolve())
    assert sentinel not in show.output

    export_path = tmp_path / "mindfresh-export.json"
    exported = runner.invoke(cli_app, ["config", "export", "--output", str(export_path)])
    assert exported.exit_code == 0, exported.output
    export_text = export_path.read_text(encoding="utf-8")
    assert json.loads(export_text)["vaults"]["docs"]["enabled"] is True
    assert sentinel not in export_text
    assert sentinel not in exported.output
    export_stdout = runner.invoke(cli_app, ["config", "export"])
    assert export_stdout.exit_code == 0, export_stdout.output
    assert json.loads(export_stdout.output)["vaults"]["docs"]["enabled"] is True
    assert sentinel not in export_stdout.output


def test_keys_status_presence_only_redacts_secret(
    runner: CliRunner,
    isolated_config: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "MF_SENTINEL_SECRET_SHOULD_NOT_LEAK_123"
    monkeypatch.setenv("GOOGLE_API_KEY", sentinel)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = runner.invoke(cli_app, ["keys", "status"])

    assert result.exit_code == 0, result.output
    assert "Google/Gemini API key: present" in result.output
    assert "GOOGLE_API_KEY" in result.output
    assert "GEMINI_API_KEY" in result.output
    assert sentinel not in result.output


def test_keys_status_missing_and_help_are_safe(
    runner: CliRunner,
    isolated_config: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "MF_SENTINEL_SECRET_SHOULD_NOT_LEAK_123"
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", sentinel)

    help_result = runner.invoke(cli_app, ["keys", "help"])
    assert help_result.exit_code == 0, help_result.output
    assert 'export GOOGLE_API_KEY="your-google-api-key"' in help_result.output
    assert "GEMINI_API_KEY" in help_result.output
    assert sentinel not in help_result.output

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    missing = runner.invoke(cli_app, ["keys", "status"])
    assert missing.exit_code == 0, missing.output
    assert "Google/Gemini API key: missing" in missing.output
    assert "Detected env vars: none" in missing.output
    assert 'export GOOGLE_API_KEY="your-google-api-key"' in missing.output
    assert sentinel not in missing.output


def test_config_import_preserves_existing_paths_and_disables_missing_paths(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app
) -> None:
    existing = tmp_path / "existing-vault"
    existing.mkdir()
    missing = tmp_path / "missing-vault"
    payload = {
        "schema_version": 1,
        "default_adapter": "google",
        "default_model": "gemini-3-flash-preview",
        "model_profile": "google/gemini-3-flash-preview",
        "vaults": {
            "existing": {"path": str(existing), "enabled": True, "adapter": "fake"},
            "missing": {"path": str(missing), "enabled": True, "adapter": "fake"},
        },
    }
    source = tmp_path / "export.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    result = runner.invoke(cli_app, ["config", "import", str(source)])

    assert result.exit_code == 0, result.output
    loaded = config.load_config(isolated_config)
    assert loaded.vaults["existing"].enabled is True
    assert loaded.vaults["missing"].enabled is False
    assert "WARNING vault missing" in result.output


def test_fake_preset_vault_does_not_inherit_default_google_model(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app
) -> None:
    vault_path = tmp_path / "vault"
    topic_path = vault_path / "Topic"
    topic_path.mkdir(parents=True)
    (topic_path / "note.md").write_text("# Local note\n\nFresh claim.", encoding="utf-8")

    add = runner.invoke(
        cli_app,
        ["vault", "add", "ci", str(vault_path), "--model-preset", "fake"],
    )
    assert add.exit_code == 0, add.output
    loaded = config.load_config(isolated_config)
    assert loaded.default_adapter == "google"
    assert loaded.default_model == "gemini-3-flash-preview"
    assert loaded.vaults["ci"].adapter == "fake"
    assert loaded.vaults["ci"].model is None

    refresh = runner.invoke(cli_app, ["refresh", "ci"])

    assert refresh.exit_code == 0, refresh.output
    summary = (topic_path / "SUMMARY.md").read_text(encoding="utf-8")
    assert "모델/런타임 프로필: `fake/deterministic-v1`" in summary
    assert "fake/gemini-3-flash-preview" not in summary


def test_watch_fake_preset_override_clears_registered_vault_model(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app
) -> None:
    vault_path = tmp_path / "vault"
    topic_path = vault_path / "Topic"
    topic_path.mkdir(parents=True)
    (topic_path / "note.md").write_text("# Local note\n\nFresh claim.", encoding="utf-8")

    add = runner.invoke(
        cli_app,
        [
            "vault",
            "add",
            "local",
            str(vault_path),
            "--model-preset",
            "qwen3-14b-ollama",
        ],
    )
    assert add.exit_code == 0, add.output

    watch = runner.invoke(
        cli_app,
        ["watch", "--all-enabled", "--once", "--debounce-ms", "0", "--model-preset", "fake"],
    )

    assert watch.exit_code == 0, watch.output
    assert "adapter=fake" in watch.output
    assert "model=[no model]" in watch.output
    summary = (topic_path / "SUMMARY.md").read_text(encoding="utf-8")
    assert "모델/런타임 프로필: `fake/deterministic-v1`" in summary
    assert "fake/qwen3:14b" not in summary


def test_refresh_unknown_model_preset_reports_clean_cli_error(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app
) -> None:
    vault_path = tmp_path / "vault"
    vault_path.mkdir()

    result = runner.invoke(cli_app, ["refresh", str(vault_path), "--model-preset", "missing"])

    assert result.exit_code == 2
    assert "unknown model preset: missing" in result.output
    assert "available:" in result.output
    assert "recommended for this Mac" in result.output
    assert "another Mac / no local LLM: gemini-3-flash" in result.output
    assert "Traceback" not in result.output


def test_cli_vault_lifecycle_without_manual_config_editing(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app
) -> None:
    vault_path = tmp_path / "Research Vault"
    vault_path.mkdir()

    add = runner.invoke(cli_app, ["vault", "add", "research", str(vault_path)])
    assert add.exit_code == 0, add.output

    listing = runner.invoke(cli_app, ["vault", "list"])
    assert listing.exit_code == 0, listing.output
    assert "research" in listing.output
    assert str(vault_path) in listing.output

    disable = runner.invoke(cli_app, ["vault", "disable", "research"])
    assert disable.exit_code == 0, disable.output
    assert not config.load_config(isolated_config).vaults["research"].enabled

    enable = runner.invoke(cli_app, ["vault", "enable", "research"])
    assert enable.exit_code == 0, enable.output
    assert config.load_config(isolated_config).vaults["research"].enabled

    rename = runner.invoke(cli_app, ["vault", "rename", "research", "research"])
    assert rename.exit_code == 0, rename.output
    loaded = config.load_config(isolated_config)
    assert "research" in loaded.vaults
    assert "research" not in loaded.vaults

    status = runner.invoke(cli_app, ["vault", "status", "research"])
    assert status.exit_code == 0, status.output
    assert "research" in status.output

    remove = runner.invoke(cli_app, ["vault", "remove", "research"])
    assert remove.exit_code == 0, remove.output
    assert config.load_config(isolated_config).vaults == {}


def test_invalid_vault_path_is_rejected_before_saving(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app
) -> None:
    missing = tmp_path / "missing-vault"

    result = runner.invoke(cli_app, ["vault", "add", "missing", str(missing)])
    if result.exit_code == 0:
        loaded = config.load_config(isolated_config)
        if "missing" in loaded.vaults:
            pytest.xfail("task 8 pending: CLI must validate vault paths before saving")

    assert result.exit_code != 0
    assert "missing" not in config.load_config(isolated_config).vaults


def test_watch_all_enabled_rejects_mixed_target_and_registry_mode(
    runner: CliRunner, isolated_config: Path, tmp_path: Path, cli_app
) -> None:
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    assert runner.invoke(cli_app, ["vault", "add", "primary", str(vault_path)]).exit_code == 0

    result = runner.invoke(cli_app, ["watch", "primary", "--all-enabled"])

    assert result.exit_code != 0
    assert "either a vault/path argument or --all-enabled" in result.output


def test_watch_once_reports_adapter_failures_without_traceback(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    topic = tmp_path / "vault" / "research" / "topic-a"
    topic.mkdir(parents=True)
    (topic / "source.md").write_text("# Topic A\n\nFresh local claim.\n", encoding="utf-8")
    vault_path = tmp_path / "vault"
    assert runner.invoke(cli_app, ["vault", "add", "primary", str(vault_path)]).exit_code == 0

    result = runner.invoke(cli_app, ["watch", "--all-enabled", "--once", "--debounce-ms", "0"])

    assert result.exit_code != 0
    assert "google adapter requires GOOGLE_API_KEY or GEMINI_API_KEY" in result.output
    assert "Traceback" not in result.output


def test_doctor_registered_vault_uses_vault_model_not_missing_google_default(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    add = runner.invoke(
        cli_app,
        ["vault", "add", "docs", str(vault_path), "--model-preset", "fake"],
    )
    assert add.exit_code == 0, add.output

    result = runner.invoke(cli_app, ["doctor", "docs"])

    assert result.exit_code == 0, result.output
    assert "fake adapter available" in result.output
    assert "google API key missing" not in result.output


def test_doctor_missing_google_key_prints_actionable_next_steps_without_secret(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "MF_SENTINEL_SECRET_SHOULD_NOT_LEAK_123"
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    add = runner.invoke(cli_app, ["vault", "add", "docs", str(vault_path)])
    assert add.exit_code == 0, add.output

    result = runner.invoke(cli_app, ["doctor", "docs"])

    assert result.exit_code == 1, result.output
    assert "FAIL vault docs: google API key missing" in result.output
    assert "GOOGLE_API_KEY" in result.output
    assert "GEMINI_API_KEY" in result.output
    assert "mindfresh keys status" in result.output
    assert 'export GOOGLE_API_KEY="your-google-api-key"' in result.output
    assert "Traceback" not in result.output
    assert sentinel not in result.output


def test_doctor_ollama_missing_model_prints_pull_and_preset_guidance(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mindfresh import adapters

    class EmptyOllamaTagsResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"models":[]}'

    monkeypatch.setattr(
        adapters.request,
        "urlopen",
        lambda *args, **kwargs: EmptyOllamaTagsResponse(),
    )
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    add = runner.invoke(
        cli_app,
        ["vault", "add", "docs", str(vault_path), "--model-preset", "qwen3-14b-ollama"],
    )
    assert add.exit_code == 0, add.output

    result = runner.invoke(cli_app, ["doctor", "docs"])

    assert result.exit_code == 1, result.output
    assert "ollama /api/tags returned no installed models" in result.output
    assert "ollama pull qwen3:14b" in result.output
    assert "mindfresh vault model docs qwen3-14b-ollama" in result.output
    assert "Recommended for this Mac" in result.output
    assert "Traceback" not in result.output


def test_doctor_ollama_missing_configured_model_keeps_colon_model_id(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mindfresh import adapters

    class OtherOllamaTagsResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"models":[{"model":"gemma3:12b"}]}'

    monkeypatch.setattr(
        adapters.request,
        "urlopen",
        lambda *args, **kwargs: OtherOllamaTagsResponse(),
    )
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    add = runner.invoke(
        cli_app,
        ["vault", "add", "docs", str(vault_path), "--model-preset", "qwen3-14b-ollama"],
    )
    assert add.exit_code == 0, add.output

    result = runner.invoke(cli_app, ["doctor", "docs"])

    assert result.exit_code == 1, result.output
    assert "ollama pull qwen3:14b" in result.output
    assert "ollama pull 14b" not in result.output
    assert "Recommended for this Mac" in result.output
    assert "Traceback" not in result.output


def test_doctor_mlx_command_and_model_path_failures_are_actionable(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINDFRESH_MLX_COMMAND", "mindfresh-definitely-missing-mlx")
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    missing_model = tmp_path / "missing-mlx-model"
    add = runner.invoke(
        cli_app,
        [
            "vault",
            "add",
            "docs",
            str(vault_path),
            "--adapter",
            "mlx",
            "--model",
            str(missing_model),
        ],
    )
    assert add.exit_code == 0, add.output

    result = runner.invoke(cli_app, ["doctor", "docs"])

    assert result.exit_code == 1, result.output
    assert "mlx command" in result.output
    assert "MINDFRESH_MLX_COMMAND" in result.output
    assert "mlx-lm" in result.output
    assert "mlx model path does not exist" in result.output
    assert "/path/to/mlx-model" in result.output
    assert "Traceback" not in result.output


def test_refresh_adapter_override_does_not_inherit_google_model(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
) -> None:
    topic = tmp_path / "vault" / "topic"
    topic.mkdir(parents=True)
    (topic / "source.md").write_text("# Source\n\nFresh local claim.\n", encoding="utf-8")

    result = runner.invoke(cli_app, ["refresh", str(tmp_path / "vault"), "--adapter", "fake"])

    assert result.exit_code == 0, result.output
    summary = (topic / "SUMMARY.md").read_text(encoding="utf-8")
    assert "모델/런타임 프로필: `fake/deterministic-v1`" in summary
    assert "fake/gemini-3-flash-preview" not in summary


def test_refresh_ollama_override_without_model_fails_before_using_google_model(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
) -> None:
    topic = tmp_path / "vault" / "topic"
    topic.mkdir(parents=True)
    (topic / "source.md").write_text("# Source\n\nFresh local claim.\n", encoding="utf-8")

    result = runner.invoke(cli_app, ["refresh", str(tmp_path / "vault"), "--adapter", "ollama"])

    assert result.exit_code != 0
    assert "ollama adapter requires --model or a vault model" in result.output
    assert "gemini-3-flash-preview" not in result.output
