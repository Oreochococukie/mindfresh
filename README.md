# mindfresh

Local-first Markdown freshness/dedupe watcher for reducing research knowledge freshness bottlenecks.

`mindfresh` watches only the vaults you explicitly register and enable. When you add a new Markdown research note to a topic folder, it refreshes that topic's generated `SUMMARY.md` and `CHANGELOG.md` while leaving your original notes untouched.

> Status: Phase 7 adapter plumbing is implemented. The current build ships the explicit vault registry, deterministic fake adapter, optional Google Gemini / MLX / Ollama adapters, model presets, topic scanner, manifest/idempotence tracking, generated latest-state/changelog writer, and bounded `watch --once` flow.

## Why this exists

Fast-moving topics like Research models, research workflows, policy policies, and AI tooling change every day. A week-old note can already be stale. `mindfresh` is designed to keep topic-level knowledge current without forcing you to reread every raw note.

The generated `SUMMARY.md` is intentionally not a short abstract. It is a Korean latest-state document that:

- preserves important source context, dates, numbers, caveats, and comparisons;
- merges semantically duplicated claims into one canonical latest claim;
- records which duplicate claims were collapsed;
- marks stale or conflicting claims instead of silently deleting them;
- keeps the raw Markdown notes untouched.

## Core behavior

```text
vault/
  research/
    topic-a/
      2026-04-24-source-a.md    # raw note, never edited
      2026-04-25-source-b.md       # raw note, never edited
      SUMMARY.md                       # generated latest-state + dedupe document
      CHANGELOG.md                     # generated change history
  .mindfresh/
    manifest.sqlite                    # internal state for this vault only
```

Flow:

1. You register a vault explicitly.
2. You enable only the vaults you want watched.
3. `mindfresh watch --all-enabled` watches enabled registered vaults only.
4. New or changed raw `.md` files trigger a per-topic refresh.
5. Generated files are excluded from source ingestion to avoid self-ingestion loops.
6. Raw notes remain byte-for-byte unchanged.

## Quick start

Install from the repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

Initialize config without hand-editing TOML:

```bash
mindfresh init
```

The default preset is `gemini-3-flash`, which uses the Google Gemini API model
`gemini-3-flash-preview`. Set one API key environment variable before live use:

```bash
export GOOGLE_API_KEY="your-google-api-key"
# GEMINI_API_KEY is also accepted.
```

Register only the vaults you want `mindfresh` to know about:

```bash
mindfresh vault add research ~/Documents/MindfreshDemoVault --model-preset gemini-3-flash
mindfresh vault list
mindfresh vault status research
```

Refresh a registered vault:

```bash
mindfresh refresh research
```

Or run with the deterministic local test adapter:

```bash
mindfresh refresh research --adapter fake
```

Run one bounded watch/refresh cycle across enabled vaults:

```bash
mindfresh watch --all-enabled --once
```

## Vault management UX

Vault management does not require editing config files:

```bash
mindfresh vault add research ~/Documents/MindfreshDemoVault
mindfresh vault model research gemini-3-flash
mindfresh vault enable research
mindfresh vault disable archive
mindfresh vault list
mindfresh vault status research
```

Model preset management:

```bash
mindfresh models list
mindfresh models set-default gemini-3-flash
mindfresh vault model research qwen3-14b-ollama
```

Watching:

```bash
mindfresh watch research --once
mindfresh watch --all-enabled --once
```

One-off explicit path watch is allowed but does not auto-register the path:

```bash
mindfresh watch ~/Documents/MindfreshDemoVault --once
```

The long-running watcher daemon is intentionally deferred; the current slice exposes `--once` so the refresh contract can be tested safely before background scheduling is added.

## Model direction

The architecture keeps model/runtime behind adapters.

Implemented adapters:

- `fake`: deterministic no-model adapter for tests and CI.
- `google` / `gemini`: Google Gemini API adapter. Default model preset is `gemini-3-flash`.
- `mlx`: optional Apple Silicon adapter through the `mlx_lm.generate` command.
- `ollama`: optional local-server adapter through Ollama's `/api/generate` endpoint.

Deferred adapter:

- `llama.cpp`: deferred unless needed.

The default live preset is `gemini-3-flash` (`google` adapter, `gemini-3-flash-preview` model). This makes another PC usable without a large local LLM. For offline/high-privacy use, pick an Ollama or MLX preset instead.

### Google Gemini API

Set an API key:

```bash
export GOOGLE_API_KEY="your-google-api-key"
# or:
export GEMINI_API_KEY="your-google-api-key"
```

Use the default preset:

```bash
mindfresh init
mindfresh vault add docs ~/Documents/vault --model-preset gemini-3-flash
mindfresh doctor docs
mindfresh refresh docs
```

The Google API host defaults to `https://generativelanguage.googleapis.com/v1beta`.
Override only when testing or proxying:

```bash
export MINDFRESH_GOOGLE_API_HOST="https://generativelanguage.googleapis.com/v1beta"
```

### Presets for smaller/local computers

List choices:

```bash
mindfresh models list
```

Built-in presets include:

- `gemini-3-flash` — default cloud model, no local VRAM requirement.
- `qwen3-14b-ollama` — smaller local Ollama preset.
- `gemma3-12b-ollama` — smaller local Ollama preset.
- `gemma4-31b-ollama` — larger local Ollama preset.
- `fake` — deterministic tests/CI.

### Gemma 4 31B via MLX

If your local model is an MLX-compatible model path, register the vault with the model path:

```bash
mindfresh vault add research ~/Documents/MindfreshDemoVault \
  --adapter mlx \
  --model /path/to/your/gemma-4-31b-mlx-model

mindfresh refresh research
```

`mindfresh` calls `mlx_lm.generate` by default. If your command differs:

```bash
export MINDFRESH_MLX_COMMAND="python3 -m mlx_lm.generate"
mindfresh refresh research
```

### Gemma 4 31B via Ollama

If your model is served by Ollama, use the Ollama model id:

```bash
mindfresh vault add research ~/Documents/MindfreshDemoVault \
  --adapter ollama \
  --model your-gemma-4-31b-model-id

mindfresh refresh research
```

`mindfresh` uses `http://localhost:11434` by default. Override it when needed:

```bash
export MINDFRESH_OLLAMA_HOST="http://127.0.0.1:11434"
mindfresh refresh research
```

Per-run overrides are also supported:

```bash
mindfresh refresh research --model-preset gemini-3-flash
mindfresh refresh research --model-preset qwen3-14b-ollama
mindfresh refresh research --adapter mlx --model /path/to/model
mindfresh watch --all-enabled --once --adapter ollama --model your-model-id
```

Runtime diagnostics are available through `doctor`:

```bash
mindfresh doctor research
```

For Google, `doctor` checks that `GOOGLE_API_KEY` or `GEMINI_API_KEY` is set. For Ollama, `doctor` checks `/api/tags` to confirm the configured model is installed. For MLX, it checks that the command is resolvable and local-looking model paths exist.

## Safety guarantees

- No automatic home/Desktop/Documents scanning.
- No automatic web/RSS/GitHub/paper crawling in v1.
- Only explicitly registered and enabled vaults are watched by `--all-enabled`.
- Each vault has its own `.mindfresh/manifest.sqlite`.
- Raw source notes are never modified, moved, renamed, or deleted.
- `SUMMARY.md` and `CHANGELOG.md` are generated files and are never re-ingested as raw sources.
- `SUMMARY.md` is a latest-state/dedupe artifact, not a lossy short summary.
- No-op refreshes should preserve generated hashes and avoid changelog noise.

## Implementation phases

See [`docs/operations/PHASES.md`](docs/operations/PHASES.md).

High-level phases:

1. Scaffold, `mindfresh init`, vault registry, status/doctor, fake adapter CI path.
2. Scanner, generated-file exclusions, source hashing, raw immutability.
3. Manifest, invalidation, no-op idempotence.
4. Latest-state/changelog schemas and atomic writer.
5. Refresh pipeline with fake adapter.
6. Watch mode with debounced per-topic refresh.
7. Google Gemini / MLX / Ollama model adapters.
8. Packaging and distribution docs.

## Testing and verification

Deterministic tests are the release gate for the local-first pipeline:

```bash
python3 -m pytest -q
```

The suite covers config/vault UX, scanner boundaries, generated-never-reingested behavior, raw-note immutability, manifest/idempotence contracts, watch debounce contracts, crash/retry expectations, and mocked live-adapter request/command boundaries. See [Testing and Verification](docs/operations/TESTING.md) for the coverage map and focused commands.

## Planning artifacts

- [Deep interview spec](docs/specs/deep-interview-markdown-knowledge-refresh.md)
- [Consensus plan](docs/plans/ralplan-markdown-knowledge-refresh.md)
- [PRD](docs/plans/prd-markdown-knowledge-refresh.md)
- [Test spec](docs/plans/test-spec-markdown-knowledge-refresh.md)

## Development policy

Every phase should be committed separately and pushed to the private GitHub remote before moving to the next phase. Commit messages follow the project's Lore Commit Protocol with rationale, constraints, confidence, test evidence, and known gaps.
