from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from mindfresh.config import AppConfig, VaultConfig
from mindfresh.vaults import enabled_vaults

from conftest import create_fixture_vault, generated_hashes


def test_all_enabled_watch_target_selection_uses_only_enabled_registered_vaults(
    tmp_path: Path,
) -> None:
    enabled_root = tmp_path / "enabled"
    disabled_root = tmp_path / "disabled"
    unrelated_home_like_root = tmp_path / "Documents" / "RandomVault"
    enabled_root.mkdir()
    disabled_root.mkdir()
    unrelated_home_like_root.mkdir(parents=True)

    cfg = AppConfig(
        vaults={
            "enabled": VaultConfig(name="enabled", path=str(enabled_root), enabled=True),
            "disabled": VaultConfig(name="disabled", path=str(disabled_root), enabled=False),
        }
    )

    selected = enabled_vaults(cfg)
    assert set(selected) == {"enabled"}
    assert selected["enabled"].path == str(enabled_root)
    assert str(unrelated_home_like_root) not in {vault.path for vault in selected.values()}


def test_watch_debounce_refreshes_enabled_vault_only(tmp_path: Path) -> None:
    if importlib.util.find_spec("mindfresh.watch") is None:
        pytest.xfail("task 10 pending: watch module/test hook has not been implemented yet")
    watch_module = importlib.import_module("mindfresh.watch")

    watch_once = getattr(watch_module, "watch_once", None)
    if watch_once is None:
        pytest.xfail("task 10 pending: expose watch_once for bounded debounce tests")

    enabled_fixture = create_fixture_vault(tmp_path / "enabled-case")
    disabled_fixture = create_fixture_vault(tmp_path / "disabled-case")
    cfg = AppConfig(
        vaults={
            "enabled": VaultConfig(name="enabled", path=str(enabled_fixture.root), enabled=True),
            "disabled": VaultConfig(
                name="disabled", path=str(disabled_fixture.root), enabled=False
            ),
        }
    )

    (enabled_fixture.topic_a / "2026-04-24-watch.md").write_text("# watched\n", encoding="utf-8")
    (disabled_fixture.topic_a / "2026-04-24-watch.md").write_text("# not watched\n", encoding="utf-8")

    watch_once(cfg, debounce_ms=25, adapter="fake", timeout_s=2.0)

    assert generated_hashes(enabled_fixture.root)
    assert generated_hashes(disabled_fixture.root) == {}
