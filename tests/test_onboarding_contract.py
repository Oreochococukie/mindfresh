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
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_FILE", cfg_path)
    return cfg_path


@pytest.fixture()
def cli_app(isolated_config: Path):
    from mindfresh import cli

    return cli.app


def test_version_option_prints_project_version(runner: CliRunner, cli_app) -> None:
    result = runner.invoke(cli_app, ["--version"])

    assert result.exit_code == 0, result.output
    assert "mindfresh" in result.output.lower()
    assert _project_version() in result.output
    assert "Traceback" not in result.output


def test_onboard_non_interactive_registers_only_explicit_vault_path(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
) -> None:
    vault_path = _make_vault(tmp_path)

    result = runner.invoke(
        cli_app,
        [
            "onboard",
            "--vault-name",
            "docs",
            "--vault-path",
            str(vault_path),
            "--model-preset",
            "fake",
            "--non-interactive",
            "--skip-doctor",
        ],
    )

    assert result.exit_code == 0, result.output
    loaded = config.load_config(isolated_config)
    assert list(loaded.vaults) == ["docs"]
    assert loaded.vaults["docs"].path == str(vault_path.resolve())
    assert loaded.vaults["docs"].adapter == "fake"
    assert loaded.vaults["docs"].model is None
    assert loaded.default_adapter == "fake"
    assert loaded.default_model is None
    assert "explicit vault" in result.output.lower()
    assert "mindfresh keys status" in result.output
    assert "mindfresh doctor docs" in result.output


def test_onboard_guided_stdin_registers_vault_without_discovery(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "home"
    for relative in ("Documents", "Desktop", "Markdown note folder", "Documents/Markdown note folder"):
        (fake_home / relative).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    vault_path = _make_vault(tmp_path)

    result = runner.invoke(
        cli_app,
        ["onboard", "--skip-doctor"],
        input=f"docs\n{vault_path}\nfake\n",
    )

    assert result.exit_code == 0, result.output
    loaded = config.load_config(isolated_config)
    assert list(loaded.vaults) == ["docs"]
    assert loaded.vaults["docs"].path == str(vault_path.resolve())
    assert loaded.vaults["docs"].adapter == "fake"
    assert str(fake_home / "Markdown note folder") not in result.output


def test_onboard_rejects_missing_vault_path_without_saving(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
) -> None:
    missing = tmp_path / "missing-vault"

    result = runner.invoke(
        cli_app,
        [
            "onboard",
            "--vault-name",
            "docs",
            "--vault-path",
            str(missing),
            "--model-preset",
            "fake",
            "--non-interactive",
            "--skip-doctor",
        ],
    )

    assert result.exit_code != 0
    assert "vault path" in result.output.lower()
    assert "exist" in result.output.lower()
    assert "docs" not in config.load_config(isolated_config).vaults


def test_onboard_output_redacts_secret_environment_values(
    runner: CliRunner,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "MF_SENTINEL_SECRET_SHOULD_NOT_LEAK_123"
    monkeypatch.setenv("GOOGLE_API_KEY", sentinel)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    vault_path = _make_vault(tmp_path)

    result = runner.invoke(
        cli_app,
        [
            "onboard",
            "--vault-name",
            "docs",
            "--vault-path",
            str(vault_path),
            "--model-preset",
            "fake",
            "--non-interactive",
            "--skip-doctor",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "GOOGLE_API_KEY" in result.output
    assert "your-google-api-key" in result.output
    assert sentinel not in result.output


def test_onboard_does_not_refresh_watch_or_create_generated_files(
    runner: CliRunner,
    tmp_path: Path,
    cli_app,
) -> None:
    vault_path = _make_vault(tmp_path)

    result = runner.invoke(
        cli_app,
        [
            "onboard",
            "--vault-name",
            "docs",
            "--vault-path",
            str(vault_path),
            "--model-preset",
            "fake",
            "--non-interactive",
            "--skip-doctor",
        ],
    )

    assert result.exit_code == 0, result.output
    assert not list(vault_path.rglob("SUMMARY.md"))
    assert not list(vault_path.rglob("CHANGELOG.md"))
    assert "watch requested:" not in result.output.lower()
    assert "refresh results:" not in result.output.lower()
    assert "mindfresh refresh docs --adapter fake" in result.output
    assert "mindfresh watch --all-enabled --once" in result.output


def test_onboard_missing_google_key_is_advisory_by_default(
    runner: CliRunner,
    isolated_config: Path,
    tmp_path: Path,
    cli_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    vault_path = _make_vault(tmp_path)

    result = runner.invoke(
        cli_app,
        [
            "onboard",
            "--vault-name",
            "docs",
            "--vault-path",
            str(vault_path),
            "--model-preset",
            "gemini-3-flash",
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "FAIL vault docs: google API key missing" in result.output
    assert "Onboarding can continue" in result.output
    assert "export GOOGLE_API_KEY" in result.output
    assert "docs" in config.load_config(isolated_config).vaults


def _make_vault(tmp_path: Path) -> Path:
    topic = tmp_path / "vault" / "topic"
    topic.mkdir(parents=True)
    (topic / "source.md").write_text("# Source\n\nFresh local claim.\n", encoding="utf-8")
    return tmp_path / "vault"


def _project_version() -> str:
    for line in Path("pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split('"', 2)[1]
    raise AssertionError("pyproject.toml has no project version")
