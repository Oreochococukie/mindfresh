from pathlib import Path

from mindfresh.config import AppConfig, ConfigError, VaultConfig, load_config, write_config


def test_write_and_load_config_atomic(tmp_path: Path):
    cfg = AppConfig(
        vaults={"research": VaultConfig(name="research", path=str(tmp_path / "vault"))},
        default_adapter="mlx",
        default_model="/models/gemma-4-31b",
    )
    out = write_config(cfg, path=tmp_path / "config.toml")
    loaded = load_config(out)
    assert out.exists()
    assert loaded.default_adapter == "mlx"
    assert loaded.default_model == "/models/gemma-4-31b"
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
