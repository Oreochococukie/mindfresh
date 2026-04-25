from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import json
import os
import shlex
from pathlib import Path
from typing import NoReturn, Optional, Sequence

import click
import typer

from .config import (
    CONFIG_ENV_VAR,
    DEFAULT_CONFIG_FILE,
    AppConfig,
    ConfigError,
    VaultConfig,
    config_from_mapping,
    config_diagnostics,
    config_json,
    describe_vault,
    load_config,
    resolve_effective_adapter_model,
    resolve_watch_targets,
    write_config,
)
from .refresh import refresh_vault
from .adapters import (
    DEFAULT_OLLAMA_HOST,
    GOOGLE_API_HOST_ENV_VAR,
    GOOGLE_API_KEY_ENV_VARS,
    MLX_COMMAND_ENV_VAR,
    OLLAMA_HOST_ENV_VAR,
    AdapterRuntimeError,
    GoogleModelInfo,
    list_google_generate_models,
)
from .model_presets import (
    DEFAULT_MODEL_PRESET,
    get_model_preset,
    list_model_presets,
    model_preset_recommendations,
)
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
models_app = typer.Typer(help="List and select model presets", no_args_is_help=True)
config_app = typer.Typer(help="Show, export, and import non-secret config", no_args_is_help=True)
keys_app = typer.Typer(help="Check API-key setup without printing secrets", no_args_is_help=True)
app.add_typer(vault_app, name="vault")
app.add_typer(models_app, name="models")
app.add_typer(config_app, name="config")
app.add_typer(keys_app, name="keys")


@app.callback()
def callback(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Config path. Overrides default and MINDFRESH_CONFIG_PATH for this command.",
    ),
    show_version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=lambda value: _version_callback(value),
        is_eager=True,
        help="Show the installed mindfresh version and exit.",
    ),
) -> None:
    ctx.obj = {"config_path": config.expanduser() if config else _default_config_file()}


@app.command()
def init(
    vault_name: Optional[str] = typer.Option(None, "--vault-name", help="Initial vault name."),
    vault_path: Optional[Path] = typer.Option(None, "--vault-path", help="Initial vault directory."),
    model_preset: str = typer.Option(
        DEFAULT_MODEL_PRESET,
        "--model-preset",
        "--preset",
        help="Model preset to use when --adapter/--model are not supplied.",
    ),
    adapter: Optional[str] = typer.Option(None, "--adapter", help="Default adapter override."),
    model_profile: Optional[str] = typer.Option(
        None,
        "--model-profile",
        help="Default model profile label.",
    ),
    model: Optional[str] = typer.Option(None, "--model", help="Optional model identifier/path."),
    enable: bool = typer.Option(True, "--enable/--disable", help="Enable the initial vault."),
) -> None:
    """Create initial config without requiring users to edit TOML by hand."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    try:
        selected_adapter, selected_model = _resolve_preset_adapter_model(
            preset_name=model_preset,
            adapter_override=adapter,
            model_override=model,
        )
    except ValueError as exc:
        _fail(str(exc))
    if selected_adapter is None:
        _fail("init requires an adapter or model preset")
    cfg.default_adapter = selected_adapter
    cfg.default_model = selected_model
    cfg.model_profile = model_profile or _profile_label(selected_adapter, selected_model)

    if vault_name is not None or vault_path is not None:
        if vault_name is None or vault_path is None:
            _fail("--vault-name and --vault-path must be provided together")
        try:
            cfg = add_vault(
                cfg,
                name=vault_name,
                path=str(vault_path),
                adapter=selected_adapter,
                model=selected_model,
                enabled=enable,
            )
        except ConfigError as exc:
            _fail(str(exc))

    written = _save_or_exit(cfg, cfg_path)
    typer.echo(f"Initialized mindfresh config: {written}")
    typer.echo("Use 'mindfresh vault ...' for normal vault changes; manual TOML editing is optional.")
    _print_doctor_summary(cfg, written)


@app.command()
def setup(
    model_preset: str = typer.Option(
        DEFAULT_MODEL_PRESET,
        "--model-preset",
        "--preset",
        help="Default model preset to store in config.",
    ),
    adapter: Optional[str] = typer.Option(None, "--adapter", help="Default adapter override."),
    model: Optional[str] = typer.Option(None, "--model", help="Optional model identifier/path."),
    vault_name: Optional[str] = typer.Option(
        None,
        "--vault-name",
        help="Explicit vault name to register. Must be used with --vault-path.",
    ),
    vault_path: Optional[Path] = typer.Option(
        None,
        "--vault-path",
        help="Explicit vault path to register. Mindfresh never auto-discovers vault paths.",
    ),
    enable: bool = typer.Option(True, "--enable/--disable", help="Enable the explicit vault."),
    replace: bool = typer.Option(False, "--replace", help="Replace an existing vault record."),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Run deterministically without prompts; missing vault flags simply skip vault registration.",
    ),
) -> None:
    """Guided, flag-first setup for a new Mac without editing TOML by hand."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    try:
        selected_adapter, selected_model = _resolve_preset_adapter_model(
            preset_name=model_preset,
            adapter_override=adapter,
            model_override=model,
        )
    except ValueError as exc:
        _fail(str(exc))
    if selected_adapter is None:
        _fail("setup requires an adapter or model preset")

    cfg.default_adapter = selected_adapter
    cfg.default_model = selected_model
    cfg.model_profile = _profile_label(selected_adapter, selected_model)

    registered_vault: Optional[str] = None
    if vault_name is not None or vault_path is not None:
        if vault_name is None or vault_path is None:
            _fail("--vault-name and --vault-path must be provided together")
        try:
            cfg = add_vault(
                cfg,
                name=vault_name,
                path=str(vault_path),
                adapter=selected_adapter,
                model=selected_model,
                enabled=enable,
                replace_existing=replace,
            )
        except ConfigError as exc:
            _fail(str(exc))
        registered_vault = vault_name

    written = _save_or_exit(cfg, cfg_path)
    typer.echo(f"Setup complete: {written}")
    typer.echo(
        f"Default model preset: {model_preset} "
        f"({selected_adapter}, {selected_model or '[no model]'})"
    )
    if registered_vault is not None:
        typer.echo(
            "Registered explicit vault: "
            f"{describe_vault(registered_vault, cfg.vaults[registered_vault])}"
        )
        typer.echo(f"Next: mindfresh doctor {registered_vault}")
    else:
        typer.echo("No vault registered. Pass --vault-name and --vault-path to add one explicitly.")
    if non_interactive:
        typer.echo("Non-interactive mode: no prompts were shown and no vault paths were inferred.")


@app.command()
def onboard(
    vault_name: Optional[str] = typer.Option(
        None,
        "--vault-name",
        help="Explicit vault name to register.",
    ),
    vault_path: Optional[Path] = typer.Option(
        None,
        "--vault-path",
        help="Explicit vault path to register. Mindfresh never auto-discovers vault paths.",
    ),
    model_preset: str = typer.Option(
        DEFAULT_MODEL_PRESET,
        "--model-preset",
        "--preset",
        help="Model preset to store for this vault and config default.",
    ),
    replace: bool = typer.Option(False, "--replace", help="Replace an existing vault record."),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Run without prompts. Requires --vault-name and --vault-path.",
    ),
    skip_doctor: bool = typer.Option(
        False,
        "--skip-doctor",
        help="Do not run the final non-mutating diagnostics step.",
    ),
    strict_doctor: bool = typer.Option(
        False,
        "--strict-doctor",
        help="Exit non-zero for any doctor failure, including a missing Google/Gemini API key.",
    ),
) -> None:
    """Beginner-friendly onboarding over explicit setup, keys, models, and doctor."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    _print_onboard_intro()

    if non_interactive:
        if vault_name is None or vault_path is None:
            _fail("onboard --non-interactive requires --vault-name and --vault-path")
    else:
        if vault_name is None:
            vault_name = typer.prompt("Vault name", default="docs")
        if vault_path is None:
            raw_path = typer.prompt(
                "Paste the exact vault folder path (Mindfresh will not search for it)"
            )
            vault_path = Path(raw_path)
        model_preset = typer.prompt("Model preset", default=model_preset or DEFAULT_MODEL_PRESET)

    if vault_name is None or vault_path is None:
        _fail("onboard requires an explicit vault name and vault path")

    try:
        selected_adapter, selected_model = _resolve_preset_adapter_model(
            preset_name=model_preset,
            adapter_override=None,
            model_override=None,
        )
    except ValueError as exc:
        _fail(str(exc))
    if selected_adapter is None:
        _fail("onboard requires a model preset with an adapter")

    cfg.default_adapter = selected_adapter
    cfg.default_model = selected_model
    cfg.model_profile = _profile_label(selected_adapter, selected_model)
    try:
        cfg = add_vault(
            cfg,
            name=vault_name,
            path=str(vault_path),
            adapter=selected_adapter,
            model=selected_model,
            enabled=True,
            replace_existing=replace,
        )
    except ConfigError as exc:
        _fail(str(exc))

    written = _save_or_exit(cfg, cfg_path)
    typer.echo(f"Onboarding config written: {written}")
    typer.echo("Registered explicit vault: " + describe_vault(vault_name, cfg.vaults[vault_name]))
    typer.echo(
        f"Selected model preset: {model_preset} "
        f"({selected_adapter}, {selected_model or '[no model]'})"
    )
    _print_onboard_key_guidance(vault_name)

    if not skip_doctor:
        _run_onboard_doctor(
            cfg,
            cfg_path,
            vault_name=vault_name,
            strict_doctor=strict_doctor,
        )
    else:
        typer.echo(f"Diagnostics skipped. Later: mindfresh doctor {vault_name}")

    _print_onboard_next_commands(vault_name)


@vault_app.command("add")
def vault_add(
    name: str,
    path: str,
    adapter: Optional[str] = typer.Option(default=None),
    model: Optional[str] = typer.Option(default=None),
    model_preset: Optional[str] = typer.Option(
        None,
        "--model-preset",
        "--preset",
        help="Use a named model preset instead of typing adapter/model manually.",
    ),
    enable: bool = typer.Option(True, "--enable/--disable", help="Enable for watch --all-enabled."),
    replace: bool = typer.Option(False, "--replace", help="Replace an existing vault record."),
) -> None:
    """Register a vault by explicit name and path."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    try:
        selected_adapter, selected_model = _resolve_preset_adapter_model(
            preset_name=model_preset,
            adapter_override=adapter,
            model_override=model,
        )
    except ValueError as exc:
        _fail(str(exc))
    try:
        cfg = add_vault(
            cfg,
            name=name,
            path=path,
            adapter=selected_adapter,
            model=selected_model,
            enabled=enable,
            replace_existing=replace,
        )
    except ConfigError as exc:
        _fail(str(exc))
    _save_or_exit(cfg, cfg_path)
    typer.echo(f"Added vault {name}: {cfg.vaults[name].path} ({'enabled' if enable else 'disabled'})")


@vault_app.command("model")
def vault_model(
    name: str,
    model_preset: str = typer.Argument(..., help="Preset from 'mindfresh models list'."),
) -> None:
    """Set one vault's adapter/model from a preset."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    vault = get_vault(cfg, name)
    if vault is None:
        _fail(f"Unknown vault: {name}")
    try:
        preset = get_model_preset(model_preset)
    except ValueError as exc:
        _fail(str(exc))
    cfg.vaults[name] = VaultConfig(
        name=vault.name,
        path=vault.path,
        enabled=vault.enabled,
        adapter=preset.adapter,
        model=preset.model,
    )
    _save_or_exit(cfg, cfg_path)
    typer.echo(f"Set vault {name} model preset: {preset.name} ({preset.adapter}, {preset.model})")


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


@models_app.command("list")
def models_list() -> None:
    """List built-in model presets."""
    _print_model_presets()


@models_app.command("google")
def models_google(
    set_default: bool = typer.Option(
        False,
        "--set-default",
        help="Prompt to select one listed Google/Gemini model and store it as the default.",
    ),
    vault_name: Optional[str] = typer.Option(
        None,
        "--vault",
        help="Prompt to select one listed Google/Gemini model for this registered vault.",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="List models only; never prompt.",
    ),
) -> None:
    """List generation-capable Google/Gemini models available to the current API key."""
    if set_default and vault_name:
        _fail("Use either --set-default or --vault, not both")
    if non_interactive and (set_default or vault_name):
        _fail("Use --non-interactive without --set-default or --vault")

    try:
        models = list_google_generate_models()
    except AdapterRuntimeError as exc:
        _fail(str(exc))
    if not models:
        _fail("No Google/Gemini models supporting generateContent were returned for this API key")

    typer.echo("Google/Gemini models available for generateContent:")
    for index, model in enumerate(models, start=1):
        display = f" — {model.display_name}" if model.display_name else ""
        limits = _format_google_model_limits(model)
        typer.echo(f"{index}. {model.model_id}{display}{limits}")

    if non_interactive:
        return
    if not set_default and vault_name is None:
        typer.echo("To store one, rerun with --set-default or --vault <vault-name>.")
        return

    selected = _prompt_google_model_choice(models)
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    if set_default:
        cfg.default_adapter = "google"
        cfg.default_model = selected.model_id
        cfg.model_profile = _profile_label("google", selected.model_id)
        written = _save_or_exit(cfg, cfg_path)
        typer.echo(f"Set default Google/Gemini model: {selected.model_id}")
        typer.echo(f"Config written: {written}")
        return

    assert vault_name is not None
    vault = get_vault(cfg, vault_name)
    if vault is None:
        _fail(f"Unknown vault: {vault_name}")
    cfg.vaults[vault_name] = VaultConfig(
        name=vault.name,
        path=vault.path,
        enabled=vault.enabled,
        adapter="google",
        model=selected.model_id,
    )
    written = _save_or_exit(cfg, cfg_path)
    typer.echo(f"Set vault {vault_name} Google/Gemini model: {selected.model_id}")
    typer.echo(f"Config written: {written}")


@models_app.command("set-default")
def models_set_default(
    model_preset: str = typer.Argument(..., help="Preset from 'mindfresh models list'."),
) -> None:
    """Set the default adapter/model without hand-editing config TOML."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    try:
        preset = get_model_preset(model_preset)
    except ValueError as exc:
        _fail(str(exc))
    cfg.default_adapter = preset.adapter
    cfg.default_model = preset.model
    cfg.model_profile = _profile_label(preset.adapter, preset.model)
    _save_or_exit(cfg, cfg_path)
    typer.echo(
        f"Set default model preset: {preset.name} "
        f"({preset.adapter}, {preset.model or '[no model]'})"
    )


@config_app.command("show")
def config_show(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print parseable non-secret JSON.",
    ),
) -> None:
    """Show current non-secret config."""
    cfg_path = _config_path()
    cfg = _load_or_exit(cfg_path)
    if json_output:
        typer.echo(config_json(cfg))
        return
    typer.echo(f"Config path: {cfg_path}")
    typer.echo(f"Default adapter: {cfg.default_adapter}")
    typer.echo(f"Default model: {cfg.default_model or 'unset'}")
    typer.echo(f"Model profile: {cfg.model_profile}")
    typer.echo(f"Configured vaults: {len(cfg.vaults)}")
    for name in vault_names(cfg):
        typer.echo(f"- {describe_vault(name, cfg.vaults[name])}")


@config_app.command("export")
def config_export(
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write non-secret config JSON to this file. Prints to stdout when omitted.",
    ),
) -> None:
    """Export non-secret config JSON for migration to another Mac."""
    cfg = _load_or_exit(_config_path())
    payload = config_json(cfg)
    if output is None:
        typer.echo(payload)
        return
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload + "\n", encoding="utf-8")
    typer.echo(f"Exported non-secret config: {output}")


@config_app.command("import")
def config_import(
    source: Path = typer.Argument(..., help="Explicit non-secret config JSON export path."),
) -> None:
    """Import non-secret config JSON; missing vault paths are disabled with a warning."""
    source = source.expanduser()
    if not source.exists():
        _fail(f"config import source does not exist: {source}")
    if not source.is_file():
        _fail(f"config import source must be a file: {source}")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(f"invalid config import JSON in {source}: {exc}")
    if not isinstance(raw, dict):
        _fail("config import JSON must be an object")
    try:
        imported = config_from_mapping(raw)
    except ConfigError as exc:
        _fail(str(exc))

    warnings = _disable_missing_imported_vaults(imported)
    written = _save_or_exit(imported, _config_path())
    typer.echo(f"Imported non-secret config: {written}")
    for warning in warnings:
        typer.secho(f"WARNING {warning}", fg=typer.colors.YELLOW)


@keys_app.command("status")
def keys_status() -> None:
    """Report whether supported API-key environment variables are present."""
    _print_google_key_status()


@keys_app.command("help")
def keys_help() -> None:
    """Show safe API-key setup instructions without reading or printing secrets."""
    typer.echo("Mindfresh API keys are configured with environment variables.")
    typer.echo("Accepted Google/Gemini env vars: " + ", ".join(GOOGLE_API_KEY_ENV_VARS))
    typer.echo('Example: export GOOGLE_API_KEY="your-google-api-key"')
    typer.echo("# GEMINI_API_KEY is also accepted if you prefer that variable name.")
    typer.echo(f"Optional API host override: export {GOOGLE_API_HOST_ENV_VAR}=<host>")
    typer.echo("Verify without printing the key: mindfresh keys status")
    typer.echo("List selectable models for this key: mindfresh models google --non-interactive")
    typer.echo("Choose a default model from the live list: mindfresh models google --set-default")
    typer.echo("Choose a vault model from the live list: mindfresh models google --vault <vault-name>")
    typer.echo("Then run diagnostics: mindfresh doctor <vault-name>")
    typer.echo("Config export/import never includes API-key values.")
    typer.echo("Secret values are never printed by keys status/help or doctor.")


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
    passes, failures = config_diagnostics(
        cfg,
        cfg_path,
        include_default_adapter=target is None,
    )
    for item in passes:
        typer.echo(f"PASS {item}")
    for item in failures:
        typer.echo(f"FAIL {item}")
    if failures:
        _print_diagnostic_next_steps(failures, passes=passes, target=target)
        raise typer.Exit(1)


@app.command()
def refresh(
    vault_or_path: str,
    topic: Optional[str] = typer.Option(default=None),
    dry_run: bool = typer.Option(False),
    adapter: Optional[str] = typer.Option(None, help="Override adapter for this run."),
    model: Optional[str] = typer.Option(None, help="Override model id/path for this run."),
    model_preset: Optional[str] = typer.Option(
        None,
        "--model-preset",
        "--preset",
        help="Use a named model preset for this run.",
    ),
    force: bool = typer.Option(False),
) -> None:
    """Refresh generated latest/dedupe artifacts with a local adapter."""
    cfg = _load_or_exit(_config_path())
    vault = get_vault(cfg, vault_or_path)
    vault_root = Path(vault.path if vault is not None else vault_or_path).expanduser()
    try:
        adapter_name, adapter_model = _resolve_adapter_model(
            cfg,
            vault,
            adapter,
            model,
            model_preset,
        )
    except ValueError as exc:
        _fail(str(exc))
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
    model_preset: Optional[str] = typer.Option(
        None,
        "--model-preset",
        "--preset",
        help="Use a named model preset for this watch run.",
    ),
    once: bool = typer.Option(False, "--once", help="Run one bounded watch cycle then exit."),
) -> None:
    """Watch one explicit vault or all enabled registered vaults."""
    cfg = _load_or_exit(_config_path())
    try:
        targets = resolve_watch_targets(cfg, target=vault_or_path, all_enabled=all_enabled)
    except ConfigError as exc:
        _fail(str(exc))
    try:
        selected_adapter, selected_model = _resolve_preset_adapter_model(
            preset_name=model_preset,
            adapter_override=adapter,
            model_override=model,
        )
    except ValueError as exc:
        _fail(str(exc))
    typer.echo(
        f"Watch requested: debounce_ms={debounce_ms}, "
        f"adapter={selected_adapter or '[per-vault/default]'}, "
        f"model={_format_model_override(selected_model, model_preset=model_preset)}"
    )
    for label, path, registered in targets:
        source = "registered" if registered else "explicit-path"
        typer.echo(f"watch_target\t{label}\t{source}\t{path}")
    if once:
        try:
            results = watch_once(
                cfg,
                target=vault_or_path,
                all_enabled=all_enabled,
                debounce_ms=debounce_ms,
                adapter=selected_adapter,
                model=selected_model,
                model_preset=model_preset,
            )
        except Exception as exc:  # CLI boundary: show clean error instead of traceback.
            _fail(str(exc))
        typer.echo(f"Refresh results: {len(results)}")
    else:
        typer.echo("Long-running watch loop is not enabled in this implementation slice; use --once.")


def _default_config_file() -> Path:
    import os

    raw = os.environ.get(CONFIG_ENV_VAR)
    return Path(raw).expanduser() if raw else DEFAULT_CONFIG_FILE


def _version_callback(value: Optional[bool]) -> None:
    if not value:
        return
    typer.echo(f"mindfresh {_package_version()}")
    raise typer.Exit()


def _package_version() -> str:
    try:
        return version("mindfresh")
    except PackageNotFoundError:
        return "0.1.0-dev"


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


def _print_onboard_intro() -> None:
    typer.echo("Mindfresh onboard")
    typer.echo("- watches only vaults you explicitly register")
    typer.echo("- leaves raw Markdown notes untouched")
    typer.echo("- uses API keys from environment variables only")
    typer.echo("- does not start a background watcher or run refresh automatically")


def _print_onboard_key_guidance(vault_name: str) -> None:
    typer.echo("API key setup (value is never typed into Mindfresh):")
    typer.echo('  export GOOGLE_API_KEY="your-google-api-key"')
    typer.echo("  # GEMINI_API_KEY is also accepted")
    typer.echo("  mindfresh keys status")
    typer.echo(f"  mindfresh models google --vault {shlex.quote(vault_name)}")
    typer.echo(f"  mindfresh doctor {vault_name}")


def _run_onboard_doctor(
    cfg: AppConfig,
    cfg_path: Path,
    *,
    vault_name: str,
    strict_doctor: bool,
) -> None:
    scoped = AppConfig(
        default_adapter=cfg.default_adapter,
        default_model=cfg.default_model,
        model_profile=cfg.model_profile,
    )
    scoped.vaults[vault_name] = cfg.vaults[vault_name]
    passes, failures = config_diagnostics(scoped, cfg_path, include_default_adapter=False)
    typer.echo("Onboard diagnostics:")
    for item in passes:
        typer.echo(f"PASS {item}")
    for item in failures:
        typer.echo(f"FAIL {item}")
    if not failures:
        return
    _print_diagnostic_next_steps(failures, passes=passes, target=vault_name)
    if strict_doctor or not _only_missing_google_key_failures(failures):
        raise typer.Exit(1)
    typer.echo("Onboarding can continue: set the API key above when you are ready for live refresh.")


def _only_missing_google_key_failures(failures: list[str]) -> bool:
    return bool(failures) and all("google API key missing" in item for item in failures)


def _print_onboard_next_commands(vault_name: str) -> None:
    typer.echo("Next safe commands:")
    typer.echo(f"  mindfresh refresh {vault_name} --adapter fake")
    typer.echo(f"  mindfresh refresh {vault_name}")
    typer.echo("  mindfresh watch --all-enabled --once")
    typer.echo("Onboarding does not run refresh or watch automatically.")


def _print_google_key_status() -> None:
    present = _present_env_vars(GOOGLE_API_KEY_ENV_VARS)
    if present:
        typer.echo("Google/Gemini API key: present")
        typer.echo("Detected env vars: " + ", ".join(present))
    else:
        typer.echo("Google/Gemini API key: missing")
        typer.echo("Detected env vars: none")
    typer.echo("Accepted env vars: " + ", ".join(GOOGLE_API_KEY_ENV_VARS))
    typer.echo("Secret values: never printed")
    if not present:
        typer.echo('Next: export GOOGLE_API_KEY="your-google-api-key"')
        typer.echo("Next: mindfresh keys status")
    else:
        typer.echo("Next: mindfresh models google --non-interactive")


def _present_env_vars(names: tuple[str, ...]) -> list[str]:
    return [name for name in names if os.environ.get(name, "").strip()]


def _print_diagnostic_next_steps(
    failures: list[str],
    *,
    passes: list[str],
    target: Optional[str],
) -> None:
    lower_failures = [item.lower() for item in failures]
    printed_recommendations = False

    typer.echo("Next steps:")
    if any("google api key missing" in item for item in lower_failures):
        typer.echo(
            "NEXT google-api-key: accepted env vars are "
            + ", ".join(GOOGLE_API_KEY_ENV_VARS)
        )
        typer.echo('NEXT google-api-key: export GOOGLE_API_KEY="your-google-api-key"')
        typer.echo("NEXT google-api-key: mindfresh keys status")
        typer.echo("NEXT google-models: list selectable models with `mindfresh models google --non-interactive`")
        typer.echo(
            "NEXT google-models: choose one with "
            f"`mindfresh models google --vault {_vault_target_or_placeholder(target)}`"
        )
        typer.echo(f"NEXT google-api-key: {_doctor_retry_command(target)}")

    if any("ollama host is not reachable" in item for item in lower_failures):
        typer.echo("NEXT ollama: start Ollama, then run `ollama list`.")
        typer.echo(
            f"NEXT ollama: or set {OLLAMA_HOST_ENV_VAR} to your Ollama host "
            f"(default {DEFAULT_OLLAMA_HOST})."
        )
        typer.echo(f"NEXT ollama: {_doctor_retry_command(target)}")

    if any(
        ("ollama model" in item and "/api/tags" in item and "not" in item)
        or "ollama /api/tags returned no installed models" in item
        for item in lower_failures
    ):
        for model in _ollama_models_from_diagnostics(failures, passes) or ["<model-id>"]:
            typer.echo(f"NEXT ollama: install the configured model: ollama pull {model}")
        typer.echo(
            "NEXT ollama: for a smaller local Mac, choose a smaller preset with "
            f"`mindfresh vault model {_vault_target_or_placeholder(target)} qwen3-14b-ollama`."
        )
        printed_recommendations = _print_model_recommendations_once(printed_recommendations)

    if any("mlx command" in item and "not" in item for item in lower_failures):
        typer.echo("NEXT mlx: install mlx-lm or point Mindfresh at your MLX command.")
        typer.echo(f'NEXT mlx: export {MLX_COMMAND_ENV_VAR}="python3 -m mlx_lm.generate"')
        typer.echo(f"NEXT mlx: {_doctor_retry_command(target)}")

    if any("mlx model path does not exist" in item for item in lower_failures):
        typer.echo("NEXT mlx: set an existing local model path for this vault/run.")
        typer.echo(
            "NEXT mlx: example `mindfresh vault add <vault-name> <vault-path> "
            "--adapter mlx --model /path/to/mlx-model`."
        )
        typer.echo(f"NEXT mlx: {_doctor_retry_command(target)}")

    if any("adapter requires a model id/path" in item for item in lower_failures):
        typer.echo("NEXT model: choose a model preset or pass an explicit --model.")
        typer.echo("NEXT model: list presets with `mindfresh models list`.")
        printed_recommendations = _print_model_recommendations_once(printed_recommendations)


def _doctor_retry_command(target: Optional[str]) -> str:
    if target:
        return f"rerun diagnostics: mindfresh doctor {shlex.quote(target)}"
    return "rerun diagnostics: mindfresh doctor"


def _vault_target_or_placeholder(target: Optional[str]) -> str:
    if target and not target.startswith(("/", ".", "~")) and "/" not in target:
        return shlex.quote(target)
    return "<vault-name>"


def _ollama_models_from_diagnostics(failures: list[str], passes: list[str]) -> list[str]:
    models: list[str] = []
    for item in failures:
        if "ollama model" in item and "/api/tags:" in item:
            models.append(item.split("/api/tags:", 1)[1].strip())
    for item in passes:
        marker = "ollama adapter configured for model:"
        if marker in item:
            models.append(item.split(marker, 1)[1].strip())
    return [model for index, model in enumerate(models) if model and model not in models[:index]]


def _print_model_recommendations_once(already_printed: bool) -> bool:
    if already_printed:
        return True
    typer.echo("Recommended for this Mac:")
    for context, preset in model_preset_recommendations():
        typer.echo(f"- {context}: {preset}")
    return True


def _format_google_model_limits(model: GoogleModelInfo) -> str:
    limits: list[str] = []
    if model.input_token_limit is not None:
        limits.append(f"input={model.input_token_limit}")
    if model.output_token_limit is not None:
        limits.append(f"output={model.output_token_limit}")
    return f" ({', '.join(limits)})" if limits else ""


def _prompt_google_model_choice(models: Sequence[GoogleModelInfo]) -> GoogleModelInfo:
    default = "1"
    raw = typer.prompt("Select model number", default=default)
    try:
        selected_index = int(str(raw).strip())
    except ValueError:
        _fail("model selection must be a number from the displayed list")
    if selected_index < 1 or selected_index > len(models):
        _fail(f"model selection must be between 1 and {len(models)}")
    return models[selected_index - 1]


def _disable_missing_imported_vaults(cfg: AppConfig) -> list[str]:
    warnings: list[str] = []
    for name in vault_names(cfg):
        vault = cfg.vaults[name]
        path = vault.resolved_path
        if path.exists() and path.is_dir():
            continue
        if vault.enabled:
            cfg.vaults[name] = VaultConfig(
                name=vault.name,
                path=vault.path,
                enabled=False,
                adapter=vault.adapter,
                model=vault.model,
            )
        warnings.append(
            f"vault {name}: imported path is missing or not a directory ({path}); "
            "imported disabled. Fix the path and run 'mindfresh vault enable "
            f"{name}' explicitly."
        )
    return warnings


def _resolve_adapter_model(
    cfg: AppConfig,
    vault: Optional[VaultConfig],
    adapter_override: Optional[str],
    model_override: Optional[str],
    model_preset: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    return resolve_effective_adapter_model(
        cfg,
        vault=vault,
        adapter_override=adapter_override,
        model_override=model_override,
        model_preset=model_preset,
    )


def _resolve_preset_adapter_model(
    *,
    preset_name: Optional[str],
    adapter_override: Optional[str],
    model_override: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    if not preset_name:
        return adapter_override, model_override
    return resolve_effective_adapter_model(
        AppConfig(),
        adapter_override=adapter_override,
        model_override=model_override,
        model_preset=preset_name,
    )


def _profile_label(adapter: str, model: Optional[str]) -> str:
    return f"{adapter}/{model or 'default'}"


def _format_model_override(model: Optional[str], *, model_preset: Optional[str]) -> str:
    if model is not None:
        return model
    if model_preset:
        return "[no model]"
    return "[per-vault/default]"


def _print_model_presets() -> None:
    default_marker = DEFAULT_MODEL_PRESET
    typer.echo("Preset\tAdapter\tModel\tDescription")
    for preset in list_model_presets():
        name = f"{preset.name} (default)" if preset.name == default_marker else preset.name
        typer.echo(
            f"{name}\t{preset.adapter}\t{preset.model or '[none]'}\t{preset.description}"
        )
    _print_model_recommendations_once(False)


def _fail(message: str) -> NoReturn:
    typer.secho(f"Error: {message}", err=True, fg=typer.colors.RED)
    raise typer.Exit(2)


def main() -> None:
    app()


if __name__ == "__main__":
    app()
