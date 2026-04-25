from pathlib import Path

from mindfresh.config import (
    AppConfig,
    ConfigError,
    VaultConfig,
    load_config,
    resolve_effective_adapter_model,
    write_config,
)


def test_write_and_load_config_atomic(tmp_path: Path):
    cfg = AppConfig(
        vaults={"research": VaultConfig(name="research", path=str(tmp_path / "vault"))},
        default_adapter="mlx",
        default_model="/models/local-test-model",
    )
    out = write_config(cfg, path=tmp_path / "config.toml")
    loaded = load_config(out)
    assert out.exists()
    assert loaded.default_adapter == "mlx"
    assert loaded.default_model == "/models/local-test-model"
    assert loaded.vaults["research"].path == str(tmp_path / "vault")


def test_validate_missing_vault_fields(tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[vaults.foo]\nenabled = 1\n", encoding="utf-8")
    try:
        load_config(bad)
    except ConfigError as exc:
        assert "vault 'foo' requires a path" in str(exc)
    else:
        raise AssertionError("expected ConfigError")


def test_effective_model_resolution_does_not_leak_google_model_to_local_adapter() -> None:
    cfg = AppConfig()

    assert resolve_effective_adapter_model(cfg, adapter_override="fake") == ("fake", None)
    assert resolve_effective_adapter_model(cfg, adapter_override="ollama") == ("ollama", None)
    assert resolve_effective_adapter_model(cfg, model_preset="qwen3-14b-ollama") == (
        "ollama",
        "qwen3:14b",
    )
    assert resolve_effective_adapter_model(
        cfg,
        adapter_override="fake",
        model_preset="gemini-3-flash",
    ) == ("fake", None)
