from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import (
    AppConfig,
    ConfigError,
    VaultConfig,
    add_vault_record,
    remove_vault_record,
    rename_vault_record,
    update_vault_enabled,
)


def vault_names(config: AppConfig) -> List[str]:
    return sorted(config.vaults.keys())


def get_vault(config: AppConfig, name_or_path: str) -> Optional[VaultConfig]:
    if name_or_path in config.vaults:
        return config.vaults[name_or_path]

    candidate = Path(name_or_path).expanduser().resolve()
    for vault in config.vaults.values():
        if vault.resolved_path == candidate:
            return vault
    return None


def add_vault(
    config: AppConfig,
    name: str,
    path: str,
    *,
    adapter: Optional[str] = None,
    model: Optional[str] = None,
    enabled: bool = True,
    replace_existing: bool = False,
) -> AppConfig:
    return add_vault_record(
        config,
        name=name,
        path=path,
        enabled=enabled,
        adapter=adapter,
        model=model,
        replace_existing=replace_existing,
    )


def remove_vault(config: AppConfig, name: str) -> AppConfig:
    updated, _removed = remove_vault_record(config, name)
    return updated


def pop_vault(config: AppConfig, name: str) -> Tuple[AppConfig, VaultConfig]:
    return remove_vault_record(config, name)


def rename_vault(config: AppConfig, old: str, new: str) -> AppConfig:
    return rename_vault_record(config, old, new)


def set_vault_enabled(config: AppConfig, name: str, enabled: bool) -> AppConfig:
    return update_vault_enabled(config, name, enabled)


def enabled_vaults(config: AppConfig) -> Dict[str, VaultConfig]:
    return {name: vault for name, vault in config.vaults.items() if vault.enabled}


__all__ = [
    "AppConfig",
    "ConfigError",
    "VaultConfig",
    "add_vault",
    "enabled_vaults",
    "get_vault",
    "pop_vault",
    "remove_vault",
    "rename_vault",
    "set_vault_enabled",
    "vault_names",
]
