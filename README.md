# mindfresh

[English](README.md) | [한국어](README.ko.md)

Local-first Markdown freshness/dedupe watcher for reducing research knowledge freshness bottlenecks.

`mindfresh` watches only the vaults you explicitly register and enable. When you add a new Markdown research note to a topic folder, it refreshes that topic's generated `SUMMARY.md` and `CHANGELOG.md` while leaving your original notes untouched.

> Status: Phase 7 adapter plumbing plus management UX slices are implemented. The current build ships the explicit vault registry, deterministic fake adapter, optional Google Gemini / MLX / Ollama adapters, model presets, guided setup/config migration, API-key presence diagnostics, actionable `doctor` remediation, topic scanner, manifest/idempotence tracking, generated latest-state/changelog writer, and bounded `watch --once` flow.

## Why this exists

Fast-moving topics like AI tools, product policies, technical standards, and research workflows change every day. A week-old note can already be stale. `mindfresh` is designed to keep topic-level knowledge current without forcing you to reread every raw note.

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

## Quick start (recommended)

Clone this repository and run the local installer. It creates a user-owned
install under `~/.mindfresh`, without `sudo`, shell-profile edits, or background
daemons. The command below is intentionally copy/pasteable for this repo.

```bash
git clone https://github.com/Oreochococukie/mindfresh.git
cd mindfresh
./install.sh
export PATH="$HOME/.mindfresh/bin:$PATH"
```

Open the expanded help first, then run the built-in neutral smoke test. The
demo path does not need an API key and does not touch your real vaults:

```bash
mindfresh --help
mindfresh demo --dry-run
```

Register an explicit vault only when the command path is verified:

```bash
mindfresh onboard \
  --vault-name research \
  --vault-path ~/Documents/ResearchVault \
  --model-preset gemini-3-flash \
  --non-interactive \
  --skip-doctor

mindfresh --version
mindfresh models list
mindfresh vault status research
mindfresh refresh research --adapter fake --dry-run
```

The default preset is `gemini-3-flash`, which uses the Google Gemini API model
`gemini-3-flash-preview`. For live Gemini use, set one API-key environment
variable, choose from the models that key can access, then run diagnostics and
refresh:

```bash
export GOOGLE_API_KEY="your-google-api-key"
# GEMINI_API_KEY is also accepted.
mindfresh keys status
mindfresh keys validate --prompt
mindfresh models google --vault research
mindfresh doctor research
mindfresh refresh research
mindfresh watch --all-enabled --once
```

To connect your real vault instead of the demo vault, run:

```bash
mindfresh onboard
# if a key/model check fails, fix it and continue from the failed step:
mindfresh onboard --resume
# or start the guided flow over:
mindfresh onboard --restart
```

The onboarding command asks you to paste the exact vault folder path. `mindfresh`
never searches your home, Desktop, Documents, or note folders. It also never
asks you to type an API-key value into Mindfresh.

### Context preservation controls

Live adapters send complete raw Markdown source text by default
(`MINDFRESH_MAX_SOURCE_CHARS=0`) and ask the model for a larger JSON response
budget (`MINDFRESH_MAX_OUTPUT_TOKENS=16384`). This matches the product goal:
non-overlapping source context should stay in the generated latest-state
document, while only duplicated, stale, or conflicting claims are collapsed or
marked.

For very long topic folders, use a model with a large context/output window and
raise the output budget if the generated `SUMMARY.md` is too short:

```bash
export MINDFRESH_MAX_SOURCE_CHARS=0
export MINDFRESH_MAX_OUTPUT_TOKENS=32768
mindfresh refresh demo
```

Only set `MINDFRESH_MAX_SOURCE_CHARS` to a positive number when you intentionally
want to cap per-file prompt size for a smaller local model.

Large topic folders also get source-context sidecars. In the default
`--preserve-mode auto`, Mindfresh writes `_generated/mindfresh/CONTEXT-*.md`
when a topic has many sources or enough raw text that one generated file would
be hard to use. These files are not summaries; they preserve ordered Markdown
chunks with source paths and hashes so non-overlapping context is not lost.

```bash
mindfresh refresh research --preserve-mode auto
mindfresh refresh research --preserve-mode sharded --context-shard-max-chars 40000
```

### Manual developer install

Use this path when contributing to this repo or debugging packaging behavior:

```bash
git clone https://github.com/Oreochococukie/mindfresh.git
cd mindfresh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
mindfresh onboard
```

### Update

From an existing checkout:

```bash
cd mindfresh
git pull
./install.sh --prefix ~/.mindfresh --no-onboard
mindfresh --version
```

### Move non-secret config to another Mac

```bash
mindfresh config export --output mindfresh-config.json
# copy mindfresh-config.json to the other Mac
mindfresh config import mindfresh-config.json
```

Exports do not include API-key values. During import, vault paths that do not
exist on the target Mac are imported as disabled and must be fixed/re-enabled
explicitly.

### Uninstall

Remove the local app install prefix. This does not delete your vault notes.

```bash
rm -rf ~/.mindfresh
```

Optional cleanup if you want to remove Mindfresh config too:

```bash
rm -rf ~/.config/mindfresh
```

Troubleshooting quick checks:

```bash
~/.mindfresh/bin/mindfresh --version
export PATH="$HOME/.mindfresh/bin:$PATH"
mindfresh keys help
mindfresh doctor <vault-name>
```

## Vault management UX

Vault management does not require editing config files:

```bash
mindfresh setup --vault-name research --vault-path ~/Documents/ResearchVault --model-preset gemini-3-flash
mindfresh config show --json
mindfresh config export --output mindfresh-config.json
mindfresh config import mindfresh-config.json
mindfresh vault add research ~/Documents/ResearchVault
mindfresh vault model research gemini-3-flash
mindfresh vault enable research
mindfresh vault disable archive
mindfresh vault list
mindfresh vault status research
mindfresh keys status
mindfresh keys help
```

Model preset management:

```bash
mindfresh models list
mindfresh models set-default gemini-3-flash
mindfresh vault model research qwen3-14b-ollama
```

`mindfresh models list` also prints "Recommended for this Mac" guidance:

- another Mac / no local LLM → `gemini-3-flash` (default Gemini API path)
- offline smaller local → `qwen3-14b-ollama` or `gemma3-12b-ollama`
- offline quality local → `gemma4-31b-ollama`
- tests/CI → `fake`

Watching:

```bash
mindfresh watch research --once
mindfresh watch --all-enabled --once
```

One-off explicit path watch is allowed but does not auto-register the path:

```bash
mindfresh watch ~/Documents/ResearchVault --once
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
mindfresh keys status
```

`mindfresh keys status` reports only presence/absence and accepted variable names.
`mindfresh keys help` prints copy/paste-safe setup commands. Neither command prints
the actual API-key value.

To list and pick from the models that your current API key can actually access:

```bash
# list only
mindfresh models google --non-interactive

# choose a repo-wide default from a numbered menu
mindfresh models google --set-default

# choose a model for one registered vault
mindfresh models google --vault docs
```

Mindfresh calls Google's model listing endpoint, shows only models that support
`generateContent`, and stores the selected model id for you. You do not need to
type model names manually.

Use the default preset:

```bash
mindfresh setup --vault-name docs --vault-path ~/Documents/vault --model-preset gemini-3-flash
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
mindfresh vault add research ~/Documents/ResearchVault \
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
mindfresh vault add research ~/Documents/ResearchVault \
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

When diagnostics fail, `doctor` prints actionable next steps instead of a
traceback, for example:

- Google/Gemini: accepted env var names, `export GOOGLE_API_KEY="your-google-api-key"`, `mindfresh keys status`, and the retry command.
- Ollama: start Ollama or set `MINDFRESH_OLLAMA_HOST`, install the configured model with `ollama pull ...`, or switch to a smaller preset.
- MLX: install/configure `mlx-lm`, set `MINDFRESH_MLX_COMMAND`, or point the vault/run at an existing local model path.

`doctor` is presence-only for secrets: it may mention variable names, but it never
prints API-key values.

## Safety guarantees

- No automatic home/Desktop/Documents scanning.
- No automatic web/RSS/GitHub/paper crawling in v1.
- `setup` writes vaults only from explicit `--vault-path` input.
- `config export` is non-secret; API keys stay per-machine.
- `keys status`, `keys help`, and `doctor` never echo API-key values.
- `config import` disables imported vaults whose paths are missing on the target Mac.
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
