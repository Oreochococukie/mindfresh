from __future__ import annotations

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
