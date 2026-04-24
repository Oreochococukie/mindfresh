from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import typer

from .config import (
    CONFIG_ENV_VAR,
    DEFAULT_CONFIG_FILE,
    AppConfig,
    ConfigError,
    VaultConfig,
    config_diagnostics,
    describe_vault,
    load_config,
    resolve_watch_targets,
    write_config,
)
from .refresh import refresh_vault
from .vaults import (
    add_vault,
    enabled_vaults,
    get_vault,
    pop_vault,
    rename_vault,
    set_vault_enabled,
    vault_names,
)
from .watch import watch_once

app = typer.Typer(help="mindfresh: local markdown freshness watcher", no_args_is_help=True)
vault_app = typer.Typer(help="Manage explicit vault registry", no_args_is_help=True)
app.add_typer(vault_app, name="vault")


@app.callback()
def callback(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Config path. Overrides default and MINDFRESH_CONFIG_PATH for this command.",
    ),
) -> None:
    ctx.obj = {"config_path": config.expanduser() if config else _default_config_file()}


@app.command()
def init(
    vault_name: Optional[str] = typer.Option(None, "--vault-name", help="Initial vault name."),
    vault_path: Optional[Path] = typer.Option(None, "--vault-path", help="Initial vault directory."),
    adapter: str = typer.Option("fake", "--adapter", help="Default adapter for generated setup."),
    model_profile: str = typer.Option("fake", "--model-profile", help="Default model profile label."),
    model: Optional[str] = typer.Option(None, "--model", help="Optional model identifier/path."),
    enable: bool = typer.Option(True, "--enable/--disable", help="Enable the initial vault."),
) -> None:
    """Create initial config without requiring users to edit TOML by hand."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    cfg.default_adapter = adapter
    cfg.default_model = model
    cfg.model_profile = model_profile

    if vault_name is not None or vault_path is not None:
        if vault_name is None or vault_path is None:
            _fail("--vault-name and --vault-path must be provided together")
        try:
            cfg = add_vault(
                cfg,
                name=vault_name,
                path=str(vault_path),
                adapter=adapter,
                model=model,
                enabled=enable,
            )
        except ConfigError as exc:
            _fail(str(exc))

    written = _save_or_exit(cfg, cfg_path)
    typer.echo(f"Initialized mindfresh config: {written}")
    typer.echo("Use 'mindfresh vault ...' for normal vault changes; manual TOML editing is optional.")
    _print_doctor_summary(cfg, written)


@vault_app.command("add")
def vault_add(
    name: str,
    path: str,
    adapter: Optional[str] = typer.Option(default=None),
    model: Optional[str] = typer.Option(default=None),
    enable: bool = typer.Option(True, "--enable/--disable", help="Enable for watch --all-enabled."),
    replace: bool = typer.Option(False, "--replace", help="Replace an existing vault record."),
) -> None:
    """Register a vault by explicit name and path."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    try:
        cfg = add_vault(
            cfg,
            name=name,
            path=path,
            adapter=adapter,
            model=model,
            enabled=enable,
            replace_existing=replace,
        )
    except ConfigError as exc:
        _fail(str(exc))
    _save_or_exit(cfg, cfg_path)
    typer.echo(f"Added vault {name}: {cfg.vaults[name].path} ({'enabled' if enable else 'disabled'})")


@vault_app.command("list")
def vault_list() -> None:
    """List configured vaults."""
    cfg = _load_or_exit(_config_path())
    if not cfg.vaults:
        typer.echo("No vaults configured")
        return
    for name in vault_names(cfg):
        typer.echo(describe_vault(name, cfg.vaults[name]))


@vault_app.command("enable")
def vault_enable(name: str) -> None:
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    try:
        cfg = set_vault_enabled(cfg, name=name, enabled=True)
    except ConfigError as exc:
        _fail(str(exc))
    _save_or_exit(cfg, cfg_path)
    typer.echo(f"Enabled vault: {name}")


@vault_app.command("disable")
def vault_disable(name: str) -> None:
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    try:
        cfg = set_vault_enabled(cfg, name=name, enabled=False)
    except ConfigError as exc:
        _fail(str(exc))
    _save_or_exit(cfg, cfg_path)
    typer.echo(f"Disabled vault: {name}")


@vault_app.command("remove")
def vault_remove(name: str) -> None:
    """Remove a vault from the registry without touching vault files."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    try:
        cfg, removed = pop_vault(cfg, name)
    except ConfigError as exc:
        _fail(str(exc))
    _save_or_exit(cfg, cfg_path)
    typer.echo(f"Removed vault {name}; files left untouched at {removed.path}")


@vault_app.command("rename")
def vault_rename(old: str, new: str) -> None:
    """Rename a vault registry entry without moving files."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    try:
        cfg = rename_vault(cfg, old=old, new=new)
    except ConfigError as exc:
        _fail(str(exc))
    _save_or_exit(cfg, cfg_path)
    typer.echo(f"Renamed vault: {old} -> {new}")


@vault_app.command("status")
def vault_status(name: Optional[str] = typer.Argument(None)) -> None:
    """Show one vault or all vault registry status."""
    cfg = _load_or_exit(_config_path())
    if name is not None:
        vault = get_vault(cfg, name)
        if vault is None:
            _fail(f"Unknown vault: {name}")
        _print_vault_status(vault.name, vault)
        return
    if not cfg.vaults:
        typer.echo("No vaults configured")
        return
    for vault_name in vault_names(cfg):
        _print_vault_status(vault_name, cfg.vaults[vault_name])


@app.command()
def status() -> None:
    """Show configured vaults, enablement, model profile, and watcher state."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    typer.echo(f"Config path: {cfg_path}")
    typer.echo(f"Default adapter: {cfg.default_adapter}")
    typer.echo(f"Default model: {cfg.default_model or 'unset'}")
    typer.echo(f"Model profile: {cfg.model_profile}")
    typer.echo(f"Configured vaults: {len(cfg.vaults)}")
    typer.echo(f"Enabled vaults: {len(enabled_vaults(cfg))}")
    typer.echo("Active watchers: not running")
    typer.echo("Last refresh: unknown")
    for name in vault_names(cfg):
        typer.echo(f"- {describe_vault(name, cfg.vaults[name])}")


@app.command()
def doctor(
    target: Optional[str] = typer.Argument(
        None,
        help="Optional registered vault name or explicit path.",
    ),
) -> None:
    """Report config/runtime availability and generated-file safety boundaries."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    if target:
        try:
            resolved = resolve_watch_targets(cfg, target=target)
        except ConfigError as exc:
            _fail(str(exc))
        scoped = AppConfig(
            default_adapter=cfg.default_adapter,
            default_model=cfg.default_model,
            model_profile=cfg.model_profile,
        )
        for label, path, registered in resolved:
            if registered:
                scoped.vaults[label] = cfg.vaults[label]
            else:
                scoped.vaults[label] = VaultConfig(name=label, path=str(path), enabled=True)
        cfg = scoped
    passes, failures = config_diagnostics(cfg, cfg_path)
    for item in passes:
        typer.echo(f"PASS {item}")
    for item in failures:
        typer.echo(f"FAIL {item}")
    if failures:
        raise typer.Exit(1)


@app.command()
def refresh(
    vault_or_path: str,
    topic: Optional[str] = typer.Option(default=None),
    dry_run: bool = typer.Option(False),
    adapter: Optional[str] = typer.Option(None, help="Override adapter for this run."),
    model: Optional[str] = typer.Option(None, help="Override model id/path for this run."),
    force: bool = typer.Option(False),
) -> None:
    """Refresh generated latest/dedupe artifacts with a local adapter."""
    cfg = _load_or_exit(_config_path())
    vault = get_vault(cfg, vault_or_path)
    vault_root = Path(vault.path if vault is not None else vault_or_path).expanduser()
    adapter_name, adapter_model = _resolve_adapter_model(cfg, vault, adapter, model)
    try:
        results = refresh_vault(
            vault_root,
            topic=topic,
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            dry_run=dry_run,
            force=force,
        )
    except Exception as exc:  # CLI boundary: show clean error instead of traceback.
        _fail(str(exc))
    if not results:
        typer.echo("No topic folders with source Markdown were found")
        return
    for result in results:
        run = f" run={result.run_id}" if result.run_id else ""
        triggers = ", ".join(result.trigger_files) if result.trigger_files else "no changed sources"
        typer.echo(f"{result.topic}: {result.status}{run} [{triggers}]")


@app.command()
def watch(
    vault_or_path: Optional[str] = typer.Argument(default=None),
    all_enabled: bool = typer.Option(False, "--all-enabled"),
    debounce_ms: int = typer.Option(500),
    adapter: Optional[str] = typer.Option(None, help="Override adapter for this watch run."),
    model: Optional[str] = typer.Option(None, help="Override model id/path for this watch run."),
    once: bool = typer.Option(False, "--once", help="Run one bounded watch cycle then exit."),
) -> None:
    """Watch one explicit vault or all enabled registered vaults."""
    cfg = _load_or_exit(_config_path())
    try:
        targets = resolve_watch_targets(cfg, target=vault_or_path, all_enabled=all_enabled)
    except ConfigError as exc:
        _fail(str(exc))
    typer.echo(
        f"Watch requested: debounce_ms={debounce_ms}, "
        f"adapter={adapter or '[per-vault/default]'}, model={model or '[per-vault/default]'}"
    )
    for label, path, registered in targets:
        source = "registered" if registered else "explicit-path"
        typer.echo(f"watch_target\t{label}\t{source}\t{path}")
    if once:
        results = watch_once(
            cfg,
            target=vault_or_path,
            all_enabled=all_enabled,
            debounce_ms=debounce_ms,
            adapter=adapter,
            model=model,
        )
        typer.echo(f"Refresh results: {len(results)}")
    else:
        typer.echo("Long-running watch loop is not enabled in this implementation slice; use --once.")


def _default_config_file() -> Path:
    import os

    raw = os.environ.get(CONFIG_ENV_VAR)
    return Path(raw).expanduser() if raw else DEFAULT_CONFIG_FILE


def _config_path() -> Path:
    ctx = click.get_current_context(silent=True)
    if ctx is not None and isinstance(ctx.obj, dict) and ctx.obj.get("config_path") is not None:
        return Path(ctx.obj["config_path"])
    return _default_config_file()


def _load_or_exit(path: Path) -> AppConfig:
    try:
        return load_config(path)
    except ConfigError as exc:
        _fail(str(exc))


def _save_or_exit(cfg: AppConfig, path: Path) -> Path:
    try:
        return write_config(cfg, path)
    except ConfigError as exc:
        _fail(str(exc))


def _print_vault_status(name: str, vault: VaultConfig) -> None:
    typer.echo(describe_vault(name, vault))
    typer.echo(f"  manifest: {vault.manifest_path}")
    typer.echo("  last_refresh: unknown")


def _print_doctor_summary(cfg: AppConfig, path: Path) -> None:
    passes, failures = config_diagnostics(cfg, path)
    for item in passes:
        typer.echo(f"PASS {item}")
    for item in failures:
        typer.echo(f"FAIL {item}")


def _resolve_adapter_model(
    cfg: AppConfig,
    vault: Optional[VaultConfig],
    adapter_override: Optional[str],
    model_override: Optional[str],
) -> tuple[str, Optional[str]]:
    adapter_name = (
        adapter_override
        or (vault.adapter if vault is not None else None)
        or cfg.default_adapter
    )
    adapter_model = (
        model_override
        or (vault.model if vault is not None else None)
        or cfg.default_model
    )
    return adapter_name, adapter_model


def _fail(message: str) -> None:
    typer.secho(f"Error: {message}", err=True, fg=typer.colors.RED)
    raise typer.Exit(2)


def main() -> None:
    app()


if __name__ == "__main__":
    app()
