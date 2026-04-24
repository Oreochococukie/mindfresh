from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Optional

from .config import AppConfig, resolve_effective_adapter_model, resolve_watch_targets
from .refresh import RefreshResult, refresh_vault


def watch_once(
    config: AppConfig,
    *,
    target: Optional[str] = None,
    all_enabled: bool = True,
    debounce_ms: int = 500,
    adapter: Optional[str] = None,
    model: Optional[str] = None,
    model_preset: Optional[str] = None,
    timeout_s: float = 2.0,
) -> list[RefreshResult]:
    """Run one bounded debounce cycle for testable/local watch behavior.

    v1 intentionally watches only explicit registry selections. With the default
    all_enabled=True this refreshes enabled vaults and ignores disabled or
    unrelated folders.
    """
    if debounce_ms > 0:
        sleep(min(debounce_ms / 1000.0, max(timeout_s, 0.0)))
    targets = resolve_watch_targets(config, target=target, all_enabled=all_enabled)
    results: list[RefreshResult] = []
    for label, path, registered in targets:
        vault = config.vaults.get(label) if registered else None
        adapter_name, adapter_model = resolve_effective_adapter_model(
            config,
            vault=vault,
            adapter_override=adapter,
            model_override=model,
            model_preset=model_preset,
        )
        results.extend(
            refresh_vault(
                Path(path),
                adapter_name=adapter_name,
                adapter_model=adapter_model,
            )
        )
    return results
