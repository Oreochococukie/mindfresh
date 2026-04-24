from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import re
import tempfile

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

import tomli_w

from .model_presets import DEFAULT_GOOGLE_ADAPTER, DEFAULT_GOOGLE_MODEL

CONFIG_ENV_VAR = "MINDFRESH_CONFIG_PATH"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "mindfresh"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.toml"
DEFAULT_ADAPTER = DEFAULT_GOOGLE_ADAPTER
DEFAULT_MODEL = DEFAULT_GOOGLE_MODEL
DEFAULT_MODEL_PROFILE = f"{DEFAULT_ADAPTER}/{DEFAULT_MODEL}"
CONFIG_SCHEMA_VERSION = 1
_VAULT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass
class VaultConfig:
    """Single explicitly registered vault."""

    name: str
    path: str
    enabled: bool = True
    adapter: Optional[str] = None
    model: Optional[str] = None

    @property
    def resolved_path(self) -> Path:
        return Path(self.path).expanduser().resolve()

    @property
    def manifest_path(self) -> Path:
        return self.resolved_path / ".mindfresh" / "manifest.sqlite"


@dataclass
class AppConfig:
    vaults: Dict[str, VaultConfig] = field(default_factory=dict)
    default_adapter: str = DEFAULT_ADAPTER
    default_model: Optional[str] = DEFAULT_MODEL
    model_profile: str = DEFAULT_MODEL_PROFILE
    schema_version: int = CONFIG_SCHEMA_VERSION

    def enabled_vault_items(self) -> List[Tuple[str, VaultConfig]]:
        return [(name, vault) for name, vault in sorted(self.vaults.items()) if vault.enabled]

    def disabled_vault_items(self) -> List[Tuple[str, VaultConfig]]:
        return [(name, vault) for name, vault in sorted(self.vaults.items()) if not vault.enabled]


class ConfigError(ValueError):
    """Raised for invalid or unsafe configuration."""


def config_path_from_env() -> Optional[Path]:
    raw = os.environ.get(CONFIG_ENV_VAR)
    return Path(raw).expanduser() if raw else None


def default_config_file() -> Path:
    return config_path_from_env() or DEFAULT_CONFIG_FILE


def validate_vault_name(name: str) -> str:
    if not _VAULT_NAME_PATTERN.match(name):
        raise ConfigError(
            "vault name must start with a letter or number and contain only letters, numbers, '-' or '_'"
        )
    return name


def validate_vault_path(path: str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise ConfigError(f"vault path does not exist: {candidate}")
    if not candidate.is_dir():
        raise ConfigError(f"vault path must be a directory: {candidate}")
    return candidate


def _coerce_toml(raw: Dict[str, Any]) -> AppConfig:
    vault_section = raw.get("vaults", {}) or {}
    if not isinstance(vault_section, dict):
        raise ConfigError("[vaults] must be a TOML table")

    vaults: Dict[str, VaultConfig] = {}
    for name, value in vault_section.items():
        validate_vault_name(name)
        if not isinstance(value, dict):
            raise ConfigError(f"vault '{name}' must be a table")
        path = value.get("path")
        if not isinstance(path, str) or not path:
            raise ConfigError(f"vault '{name}' requires a path string")

        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"vault '{name}' enabled must be boolean")

        adapter = value.get("adapter")
        if adapter is not None and not isinstance(adapter, str):
            raise ConfigError(f"vault '{name}' adapter must be a string")

        model = value.get("model")
        if model is not None and not isinstance(model, str):
            raise ConfigError(f"vault '{name}' model must be a string")

        vaults[name] = VaultConfig(
            name=name,
            path=path,
            enabled=enabled,
            adapter=adapter,
            model=model,
        )

    default_adapter = raw.get("default_adapter", DEFAULT_ADAPTER)
    default_model = raw.get("default_model")
    model_profile = raw.get("model_profile", DEFAULT_MODEL_PROFILE)
    schema_version = raw.get("schema_version", CONFIG_SCHEMA_VERSION)
    if not isinstance(default_adapter, str):
        raise ConfigError("default_adapter must be a string")
    if default_model is not None and not isinstance(default_model, str):
        raise ConfigError("default_model must be a string")
    if not isinstance(model_profile, str):
        raise ConfigError("model_profile must be a string")
    if not isinstance(schema_version, int):
        raise ConfigError("schema_version must be an integer")

    return AppConfig(
        vaults=vaults,
        default_adapter=default_adapter,
        default_model=default_model,
        model_profile=model_profile,
        schema_version=schema_version,
    )


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load config from TOML path; return empty config if missing."""
    cfg_path = path or default_config_file()
    if not cfg_path.exists():
        return AppConfig()

    try:
        with cfg_path.open("rb") as fp:
            raw = tomllib.load(fp)
    except Exception as exc:
        raise ConfigError(f"invalid TOML in {cfg_path}: {exc}") from exc

    return _coerce_toml(raw)


def write_config(config: AppConfig, path: Optional[Path] = None) -> Path:
    """Atomically write config to disk using a same-directory temp file."""
    cfg_path = path or default_config_file()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    payload: Dict[str, Any] = {
        "schema_version": config.schema_version,
        "default_adapter": config.default_adapter,
        **({"default_model": config.default_model} if config.default_model is not None else {}),
        "model_profile": config.model_profile,
        "vaults": {
            name: {
                "path": vault.path,
                "enabled": vault.enabled,
                **({"adapter": vault.adapter} if vault.adapter is not None else {}),
                **({"model": vault.model} if vault.model is not None else {}),
            }
            for name, vault in sorted(config.vaults.items(), key=lambda kv: kv[0])
        },
    }
    toml_text = tomli_w.dumps(payload)

    tmp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=cfg_path.parent,
            delete=False,
            encoding="utf-8",
            prefix=f".{cfg_path.name}.",
            suffix=".tmp",
        ) as fp:
            fp.write(toml_text)
            fp.flush()
            os.fsync(fp.fileno())
            tmp_name = fp.name
        os.replace(tmp_name, cfg_path)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return cfg_path


def add_vault_record(
    config: AppConfig,
    *,
    name: str,
    path: str,
    enabled: bool = True,
    adapter: Optional[str] = None,
    model: Optional[str] = None,
    replace_existing: bool = False,
) -> AppConfig:
    validate_vault_name(name)
    if name in config.vaults and not replace_existing:
        raise ConfigError(f"vault '{name}' already exists")
    resolved = validate_vault_path(path)
    config.vaults[name] = VaultConfig(
        name=name,
        path=str(resolved),
        enabled=enabled,
        adapter=adapter,
        model=model,
    )
    return config


def require_vault(config: AppConfig, name: str) -> VaultConfig:
    vault = config.vaults.get(name)
    if vault is None:
        raise ConfigError(f"vault '{name}' not found")
    return vault


def update_vault_enabled(config: AppConfig, name: str, enabled: bool) -> AppConfig:
    vault = require_vault(config, name)
    config.vaults[name] = replace(vault, enabled=enabled)
    return config


def remove_vault_record(config: AppConfig, name: str) -> Tuple[AppConfig, VaultConfig]:
    vault = require_vault(config, name)
    del config.vaults[name]
    return config, vault


def rename_vault_record(config: AppConfig, old: str, new: str) -> AppConfig:
    vault = require_vault(config, old)
    validate_vault_name(new)
    if new in config.vaults:
        raise ConfigError(f"vault '{new}' already exists")
    del config.vaults[old]
    config.vaults[new] = replace(vault, name=new)
    return config


def resolve_watch_targets(
    config: AppConfig,
    *,
    target: Optional[str] = None,
    all_enabled: bool = False,
) -> List[Tuple[str, Path, bool]]:
    """Resolve safe watch targets without auto-discovering user folders."""
    if all_enabled:
        if target:
            raise ConfigError("Use either a vault/path argument or --all-enabled, not both")
        targets = [(name, vault.resolved_path, True) for name, vault in config.enabled_vault_items()]
        if not targets:
            raise ConfigError("no enabled registered vaults; add and enable a vault first")
        return targets

    if not target:
        raise ConfigError("watch requires a registered vault name, explicit path, or --all-enabled")

    vault = config.vaults.get(target)
    if vault is not None:
        return [(target, vault.resolved_path, True)]

    return [(str(validate_vault_path(target)), validate_vault_path(target), False)]


def describe_vault(name: str, vault: VaultConfig) -> str:
    enabled = "enabled" if vault.enabled else "disabled"
    adapter = vault.adapter or "default"
    model = vault.model or "default"
    return f"{name}: {vault.path} ({enabled}, adapter={adapter}, model={model})"


def config_diagnostics(config: AppConfig, config_path: Path) -> Tuple[List[str], List[str]]:
    passes = [f"config path: {config_path}"]
    failures: List[str] = []
    if config_path.exists():
        passes.append("config file readable")
    else:
        passes.append("config file not created yet")

    if config.default_adapter == "fake":
        passes.append("fake adapter available")
    else:
        passes.append(f"configured default adapter: {config.default_adapter}")
    from .adapters import adapter_diagnostics

    adapter_passes, adapter_failures = adapter_diagnostics(
        config.default_adapter,
        model=config.default_model,
    )
    passes.extend(f"default adapter: {item}" for item in adapter_passes)
    failures.extend(f"default adapter: {item}" for item in adapter_failures)

    for name, vault in sorted(config.vaults.items()):
        path = vault.resolved_path
        if path.exists() and path.is_dir():
            passes.append(f"vault {name}: path exists")
        else:
            failures.append(f"vault {name}: missing path {path}")
        if path.exists() and os.access(path, os.W_OK):
            passes.append(f"vault {name}: generated paths appear writable")
        elif path.exists():
            failures.append(f"vault {name}: path is not writable {path}")
        passes.append(
            f"vault {name}: generated files ignored: SUMMARY.md, CHANGELOG.md, .mindfresh/**"
        )
        vault_adapter = vault.adapter or config.default_adapter
        vault_model = vault.model or config.default_model
        adapter_passes, adapter_failures = adapter_diagnostics(
            vault_adapter,
            model=vault_model,
        )
        passes.extend(f"vault {name}: {item}" for item in adapter_passes)
        failures.extend(f"vault {name}: {item}" for item in adapter_failures)
    return passes, failures


def config_json(config: AppConfig) -> str:
    return json.dumps(
        {
            "schema_version": config.schema_version,
            "default_adapter": config.default_adapter,
            "default_model": config.default_model,
            "model_profile": config.model_profile,
            "vaults": {
                name: {
                    "path": vault.path,
                    "enabled": vault.enabled,
                    "adapter": vault.adapter,
                    "model": vault.model,
                }
                for name, vault in sorted(config.vaults.items())
            },
        },
        indent=2,
        sort_keys=True,
    )
