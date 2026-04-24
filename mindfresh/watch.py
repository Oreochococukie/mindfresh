from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Optional

from .config import AppConfig, resolve_watch_targets
from .refresh import RefreshResult, refresh_vault


def watch_once(
    config: AppConfig,
    *,
    target: Optional[str] = None,
    all_enabled: bool = True,
    debounce_ms: int = 500,
    adapter: str = "fake",
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
    for _label, path, _registered in targets:
        results.extend(refresh_vault(Path(path), adapter_name=adapter))
    return results
