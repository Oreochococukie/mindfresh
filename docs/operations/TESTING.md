# Testing and Verification

`mindfresh` uses deterministic pytest coverage first, then optional local-model smoke tests after the fake adapter pipeline is stable.

## Core command

```bash
python3 -m pytest -q
```

Use `python3` in this repository because the worker/runtime environment does not provide a `python` shim.

## Coverage map

The pytest suite is organized around the PRD/test-spec invariants:

- `tests/test_config_ux.py` — first-run config creation and vault lifecycle UX without hand-editing config.
- `tests/test_scanner_boundaries.py` — generated/internal/hidden exclusions, generated-never-reingested behavior, and raw-note immutability for scanning.
- `tests/test_refresh_integration_contract.py` — fake refresh, manifest, idempotence, single-topic refresh isolation, and crash/retry contracts.
- `tests/test_watch_contract.py` — enabled-vault allowlist semantics and a bounded watch debounce contract.

All Phase 1 local-refresh contracts are expected to pass. If a future phase introduces optional live-model tests, keep those separate from the deterministic fake-adapter suite.

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

## Manual fake-adapter smoke after refresh/watch integration

```bash
tmpdir=$(mktemp -d)
config="$tmpdir/mindfresh.toml"
vault="$tmpdir/vault"
mkdir -p "$vault/research/topic-a"
printf '# Topic A notes\n\nNew local generation note.\n' > "$vault/research/topic-a/source.md"

python3 -m mindfresh --config "$config" init
python3 -m mindfresh --config "$config" vault add research "$vault"
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

Live MLX/Ollama tests are manual/local only and are not required for CI:

```bash
python3 -m mindfresh refresh research --adapter mlx --topic research/topic-a
python3 -m mindfresh refresh research --adapter ollama --topic research/topic-a
```

Record latency, memory warnings, generated sections, source references, and any missed stale/conflict claims.
