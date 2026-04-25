# Testing and Verification

`mindfresh` uses deterministic pytest coverage first, then optional local-model smoke tests after the fake adapter pipeline is stable.

## Core command

```bash
python3 -m pytest -q
```

Use `python3` in this repository because the worker/runtime environment does not provide a `python` shim.

## Coverage map

The pytest suite is organized around the PRD/test-spec invariants:

- `tests/test_config_ux.py` — first-run setup, non-secret config show/export/import, API-key presence diagnostics, actionable doctor remediation, model-preset recommendations, secret redaction, and vault lifecycle UX without hand-editing config.
- `tests/test_scanner_boundaries.py` — generated/internal/hidden exclusions, generated-never-reingested behavior, and raw-note immutability for scanning.
- `tests/test_refresh_integration_contract.py` — fake refresh, manifest, idempotence, single-topic refresh isolation, and crash/retry contracts.
- `tests/test_watch_contract.py` — enabled-vault allowlist semantics and a bounded watch debounce contract.
- `tests/test_live_adapters.py` — mocked Ollama HTTP request shape, mocked MLX command invocation, and registered vault model selection.

All deterministic local-refresh contracts are expected to pass. Live-model runtime tests remain manual because they depend on local MLX/Ollama installation and the user's downloaded model.

## Expected local verification during recovery work

Run the full suite:

```bash
python3 -m pytest -q
```

Run focused contracts while implementing a lane:

```bash
python3 -m pytest -q tests/test_config_ux.py
python3 -m pytest -q tests/test_scanner_boundaries.py
python3 -m pytest -q tests/test_refresh_integration_contract.py
python3 -m pytest -q tests/test_watch_contract.py
```

## Focused setup/config migration smoke

Use this when changing the management UX surface:

```bash
tmpdir=$(mktemp -d)
config="$tmpdir/mindfresh.toml"
vault="$tmpdir/vault"
export_file="$tmpdir/mindfresh-export.json"
mkdir -p "$vault/research/topic-a"
printf '# Topic A notes\n\nNew local generation note.\n' > "$vault/research/topic-a/source.md"

python3 -m mindfresh --config "$config" setup \
  --vault-name research \
  --vault-path "$vault" \
  --model-preset fake \
  --non-interactive
python3 -m mindfresh --config "$config" config show --json
python3 -m mindfresh --config "$config" keys status
python3 -m mindfresh --config "$config" config export --output "$export_file"
python3 -m mindfresh --config "$tmpdir/imported.toml" config import "$export_file"
python3 -m mindfresh --config "$tmpdir/imported.toml" refresh research
```

Pass criteria:

1. `setup` registers only the explicit `--vault-path`.
2. `config show --json` and `config export` are parseable and contain no API-key values.
3. `keys status` reports presence/absence only and never prints actual API-key values.
4. `config import` preserves existing paths, but imported missing paths are disabled with a warning.
5. Fake refresh succeeds from the imported config.

## Focused key/model/doctor diagnostics smoke

Use this when changing API-key, model preset, or `doctor` remediation output:

```bash
tmpdir=$(mktemp -d)
config="$tmpdir/mindfresh.toml"
vault="$tmpdir/vault"
mkdir -p "$vault"
unset GOOGLE_API_KEY GEMINI_API_KEY

python3 -m mindfresh --config "$config" setup \
  --vault-name docs \
  --vault-path "$vault" \
  --model-preset gemini-3-flash \
  --non-interactive
python3 -m mindfresh --config "$config" keys status
python3 -m mindfresh --config "$config" keys help
python3 -m mindfresh --config "$config" models list
python3 -m mindfresh --config "$config" doctor docs || true
```

Pass criteria:

1. `keys status/help` mention `GOOGLE_API_KEY` and `GEMINI_API_KEY` but never print secret values.
2. `models list` includes "Recommended for this Mac" guidance for cloud, smaller local, quality local, and fake presets.
3. Missing Google/Gemini credentials in `doctor` produce actionable next steps: export command, `mindfresh keys status`, and retry command.
4. `doctor` exits non-zero on failing diagnostics without a traceback.

## Manual fake-adapter smoke after refresh/watch integration

```bash
tmpdir=$(mktemp -d)
config="$tmpdir/mindfresh.toml"
vault="$tmpdir/vault"
mkdir -p "$vault/research/topic-a"
printf '# Topic A notes\n\nNew local generation note.\n' > "$vault/research/topic-a/source.md"

python3 -m mindfresh --config "$config" setup \
  --vault-name research \
  --vault-path "$vault" \
  --model-preset fake \
  --non-interactive
python3 -m mindfresh --config "$config" refresh research --adapter fake
python3 -m mindfresh --config "$config" refresh research --adapter fake
python3 -m mindfresh --config "$config" watch --all-enabled --once --adapter fake
```

Pass criteria:

1. `SUMMARY.md` and `CHANGELOG.md` are created only in topic folders with raw notes.
2. Generated files include `mindfresh_generated: true` frontmatter.
3. Raw source Markdown hashes are unchanged before/after refresh.
4. Re-running refresh with no source/config change preserves generated file hashes.
5. `watch --all-enabled` observes only explicitly registered and enabled vaults.

## Optional live-model smoke

Live MLX/Ollama tests are manual/local only and are not required for CI. Use the model path/id for the locally downloaded Gemma 4 31B model.

```bash
# MLX model path
python3 -m mindfresh refresh research \
  --adapter mlx \
  --model /path/to/your/gemma-4-31b-mlx-model \
  --topic research/topic-a

# Ollama model id
python3 -m mindfresh refresh research \
  --adapter ollama \
  --model your-gemma-4-31b-model-id \
  --topic research/topic-a
```

Record latency, memory warnings, generated sections, source references, and any missed stale/conflict claims. Keep these manual results out of CI unless the runtime/model is available in the target environment.
