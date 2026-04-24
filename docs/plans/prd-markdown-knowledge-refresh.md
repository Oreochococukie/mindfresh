# PRD: Markdown Knowledge Refresh (`mindfresh` v1)

## Metadata

- Source requirements: `.omx/specs/deep-interview-markdown-knowledge-refresh.md`
- Context snapshot: `.omx/context/markdown-knowledge-refresh-20260424T071810Z.md`
- Planning mode: `$ralplan` consensus, RALPLAN-DR short mode
- Product type: greenfield local CLI/daemon
- Date: 2026-04-24

## Problem

The user manages many fast-changing research topics in Markdown/Markdown note folder-style folders. Existing notes become stale as new model, Research node, policy, or policy-platform information arrives. The bottleneck is not saving notes; it is re-reading and reconciling them repeatedly.

## V1 Goal

Build a local-first tool, `mindfresh`, that watches topic folders for user-added Markdown notes and directly updates generated `SUMMARY.md` and `CHANGELOG.md` files for that topic while never modifying raw source notes.

## Non-goals

1. No automatic web/RSS/paper/GitHub/Research-registry crawling in v1.
2. No modification, deletion, movement, or renaming of raw source Markdown notes.
3. No requirement to build an Markdown note folder plugin, GUI, vector DB, or RAG search in v1.
4. No cloud/paid API requirement in v1.
5. No guarantee that generated summaries reflect the whole internet; v1 freshness is defined only relative to local Markdown inputs in the watched vault.

## Product Principles

1. **Freshness-first:** newly added/changed local Markdown must be reflected quickly in generated topic state.
2. **Raw immutability:** raw notes are read-only. Generated files and internal manifests are the only writable artifacts.
3. **Low cognitive overhead:** generated summaries should reduce reading and reconciliation effort.
4. **Local-first, adapter-backed inference:** model/runtime can change without changing scanner/manifest/writer correctness.
5. **Deterministic shell around LLM:** source detection, hashing, idempotence, generated-file boundaries, and atomic writes must be testable without a live LLM.

## Users / Use Cases

### Primary user

A power user/researcher maintaining a local Markdown vault across topics such as:

```text
vault/research/topic-a/
vault/research/topic-b/
vault/policy/policy-platform/
```

### Core use cases

1. User drops a new `.md` research note into `vault/research/topic-a/`.
2. `mindfresh watch vault/` detects the file and refreshes only that topic folder.
3. `SUMMARY.md` reflects current conclusions and stale/conflicting claims.
4. `CHANGELOG.md` records what changed, why, and which source files triggered it.
5. User reads `SUMMARY.md` + latest changelog entry instead of all raw notes.

## V1 Functional Requirements

### Distribution UX / no-manual-config requirement

Because this project may be distributed to other users, normal users must not need to hand-edit config files. The product UX should treat config as an internal implementation detail and expose vault/model setup through commands and, later, a lightweight local UI.

Required UX layers:

1. **First-run wizard:** `mindfresh init` walks the user through choosing vault folders, naming them, enabling/disabling them, selecting adapter/model profile, and running a dry-run/doctor check.
2. **Vault manager commands:** `mindfresh vault add/list/enable/disable/remove/rename/status` cover everyday vault management without opening config.
3. **Interactive CLI prompts:** if required options are missing, prompt with sensible defaults instead of failing with config instructions.
4. **Status dashboard:** `mindfresh status` shows watched vaults, last refresh time, changed topics, model profile, and any errors.
5. **Safe tray/menubar app as post-core UX:** after CLI pipeline is stable, add a tiny macOS menubar/controller UI for start/stop watching, add vault, enable/disable vault, open generated summary, and view errors. This UI should call the same core library/CLI, not fork logic.

Config file requirements:

- Config remains readable/exportable for power users, but docs should frame it as optional advanced usage.
- All config mutations should be done through atomic writes to avoid corrupting user setup.
- The app should validate vault paths before saving.
- The app must require explicit user selection for each watched vault; no home/Desktop/Documents auto-discovery.

Recommended phased UX:

- v1.0 developer/MVP: CLI wizard + vault manager + status/doctor.
- v1.1 local-user polish: optional menubar app or simple local web UI wrapping the same daemon.
- v2.0 Markdown note folder plugin only if core workflow proves useful.

### Multi-vault selection / allowlist

The user may have many Markdown/Markdown note folder vaults. `mindfresh` must watch **only explicitly registered or explicitly passed vaults**. It must never auto-discover and watch all folders under Desktop, Documents, iCloud, or the user home directory.

Recommended registry location:

```toml
# ~/.config/mindfresh/config.toml
[vaults.research]
path = "<user-home>/Markdown note folder/Research"
enabled = true
adapter = "mlx"
model = "<user-home>/models/gemma4-31b"

[vaults.policy]
path = "<user-home>/Markdown note folder/Policy"
enabled = true
adapter = "mlx"
model = "<user-home>/models/gemma4-31b"

[vaults.archive]
path = "<user-home>/Markdown note folder/Archive"
enabled = false
```

Vault commands:

- `mindfresh init` starts an interactive setup wizard.
- `mindfresh vault add <name> <path>` registers a vault.
- `mindfresh vault enable <name>` enables watch eligibility.
- `mindfresh vault disable <name>` prevents accidental watching.
- `mindfresh vault list` shows configured vaults and enabled status.
- `mindfresh watch <name>` watches one registered vault.
- `mindfresh watch --all-enabled` watches only enabled registered vaults.
- `mindfresh watch <path>` may watch an explicit path for one-off use but must not add it to the registry unless `vault add` is used.

Each vault keeps its own `.mindfresh/manifest.sqlite` under that vault root. There is no shared manifest across vaults.

### CLI

- `mindfresh refresh <vault-name-or-path> [--topic <path>] [--dry-run] [--adapter fake|mlx|ollama]`
- `mindfresh watch <vault-name-or-path> [--debounce-ms <n>] [--adapter fake|mlx|ollama]`
- `mindfresh watch --all-enabled [--debounce-ms <n>]`
- `mindfresh init`
- `mindfresh vault add|list|enable|disable|remove|rename|status ...`
- `mindfresh status`
- `mindfresh doctor` reports config, model/runtime availability, writable generated-file paths, and ignored generated files.

### Topic detection

A topic folder is any directory under the vault root that contains at least one raw source `.md` file after exclusions.

Source exclusions:

- `SUMMARY.md`
- `CHANGELOG.md`
- `.mindfresh/**`
- dot directories
- `_generated/**` and `_review/**` if present
- any `.md` with frontmatter `mindfresh_generated: true`

### Generated output

`SUMMARY.md` must include generated frontmatter:

```yaml
---
mindfresh_generated: true
mindfresh_kind: summary
mindfresh_topic: <relative topic path>
mindfresh_run_id: <run id>
---
```

Required sections:

1. Current conclusion
2. What changed recently
3. Stable facts retained
4. Stale or conflicting claims
5. Open questions / next checks
6. Sources considered
7. Last refreshed metadata

`CHANGELOG.md` must include generated frontmatter:

```yaml
---
mindfresh_generated: true
mindfresh_kind: changelog
mindfresh_topic: <relative topic path>
---
```

Each run entry must include:

- ISO timestamp and run ID
- trigger file(s)
- summary delta
- updated claims
- stale/conflicting claims
- source references with path + hash prefix
- model/runtime profile

### Freshness semantics

- **Recent info:** source notes whose hash is new or changed since the topic's last successful run.
- **Fresh summary:** generated `SUMMARY.md` includes all recent info judged material by the summarizer and records the latest run ID.
- **Changed:** recent info materially changes a current conclusion or adds a new important claim.
- **Conflict:** recent info contradicts or weakens a claim from previous summary/source notes.
- **Stale-risk:** previous summary contains claims that are older than recent conflicting/evolving information but cannot be fully resolved from local inputs.
- **Stable retained:** previous summary claims that remain supported and are not contradicted by recent inputs.

Rewrite policy:

- `SUMMARY.md` is rewritten as the current topic state.
- `CHANGELOG.md` is append-only/prepend-only by run entry.
- Stable facts should be retained unless contradicted or superseded.
- Conflicts must be surfaced, not silently collapsed.


### Freshness transition table

| Previous state | New input condition | New state | Required output behavior |
|---|---|---|---|
| none | first successful refresh | fresh | Create full `SUMMARY.md` and first `CHANGELOG.md` entry. |
| fresh | no source/config change | fresh | Preserve generated hashes; do not add changelog noise. |
| fresh | new/changed source adds material claim | changed | Rewrite summary current state and add changelog delta. |
| fresh/changed | new/changed source contradicts previous claim | conflicts | Keep conflict visible in summary and changelog with source references. |
| fresh/changed/conflicts | old claim is weakened but not locally resolvable | stale-risk | Mark stale-risk; do not silently delete the old claim. |
| conflicts/stale-risk | later source resolves contradiction | changed or fresh | Record resolution in changelog and update summary state. |

Executor rule: do not invent additional freshness states in v1 without updating PRD, test spec, and manifest schema.

### Manifest

Store internal state at `.mindfresh/manifest.sqlite` under vault root.

Manifest records:

- manifest schema version, starting at `1`
- hash algorithm, fixed to `sha256` for v1
- topic path
- source file path, size, mtime, SHA-256
- generated file path and SHA-256 before/after
- run ID, timestamp, adapter/model config hash
- trigger reason: new source, changed source, config/model change, forced refresh

Model/config invalidation:

- Invalidation key = `sha256(prompt_schema_version + adapter_name + model_profile + adapter_config + source_hashes)`.
- If source hashes are unchanged but prompt schema/model/runtime config hash changes, either regenerate or record a clear no-regeneration decision in the manifest.
- V1 default: regenerate on prompt schema changes; record-only on model patch-version changes unless `--force` is used.

### Atomicity and crash safety

All generated writes must use:

1. render content in memory;
2. write to temp file in same directory;
3. fsync temp file where practical;
4. atomic rename over generated target;
5. compute final generated hashes;
6. update manifest after successful generated writes.

Crash/retry rule:

- If process crashes before manifest update, the next run must detect generated/source hash mismatch and converge without corrupting raw files.
- Raw source file hashes before and after a run must match.

### Summarizer adapters

- `fake`: deterministic adapter required for tests and CI; no model dependency.
- `mlx`: default planned local adapter using `mlx-lm` where available.
- `ollama`: fallback local-server adapter.
- `llama.cpp`: planned post-v1 adapter unless explicitly scoped in execution.

Model policy:

- Default quality target: Gemma 4 26B A4B IT Thinking quantized for MLX if available in compatible format.
- Quality mode: Gemma 4 31B IT Thinking only after benchmark shows material gain over 26B A4B. Benchmark gate: 31B must improve human-rated fixture quality by at least one severity level on stale/conflict detection or materially reduce missed-change cases without exceeding an operator-accepted latency/memory budget.
- Fast mode: smaller local model profile for frequent background refresh.
- Execution must not make 31B the default without benchmark evidence. Gemma 4 26B A4B availability must be capability-detected at runtime/setup, never assumed.

## RALPLAN-DR Options

### Option A — Python CLI/daemon + MLX-first adapter + SQLite manifest — Chosen

Pros:

- Aligns with MLX/`mlx-lm` Python ecosystem.
- Enables fake adapter and test-first deterministic pipeline.
- Keeps runtime/model swappable.
- SQLite transactions support watch-mode reliability.

Cons:

- CLI UX before Markdown note folder-native UX.
- MLX model availability must be validated.
- SQLite adds small operational complexity.

### Option B — Node/TypeScript watcher + Ollama HTTP adapter

Pros:

- Simple watcher ecosystem and HTTP local-server flow.
- Easier future Markdown note folder plugin reuse.

Cons:

- Less direct control over MLX prompt cache/quantization/runtime behavior.
- Depends on Ollama service lifecycle.
- Harder to keep model/runtime internals close to Python ML tooling.

### Option C — Markdown note folder plugin first

Pros:

- Best user workflow integration.

Cons:

- Premature UI/plugin scope before core pipeline is proven.
- More preference-dependent design.

## External Evidence

- Google AI model card says Gemma 4 has E2B/E4B/26B A4B/31B sizes, up to 256K context, system-role support, and Apache 2.0 license: https://ai.google.dev/gemma/docs/core/model_card_4
- DeepMind Gemma 4 page positions 26B/31B for personal computers/local-first AI servers and shows modest benchmark deltas between 31B and 26B A4B: https://deepmind.google/models/gemma/gemma-4/
- MLX is Apple-Silicon-native with Python API and unified memory: https://github.com/ml-explore/mlx
- `mlx-lm` supports Python API, quantization, prompt caching, and rotating KV cache controls: https://github.com/ml-explore/mlx-lm
- Ollama Apple Silicon supports built-in Metal, and Ollama's MLX preview uses unified memory and cache improvements: https://docs.ollama.com/development and https://ollama.com/blog/mlx
- llama.cpp supports Apple Silicon via ARM NEON/Accelerate/Metal, GGUF, and low-bit quantization: https://github.com/ggml-org/llama.cpp

## Implementation Milestones

1. **Project scaffold and fake/no-model CI path**
   - Python package, CLI skeleton, tests.
   - `fake` adapter is mandatory before live model work.

2. **Scanner and generated-source boundary**
   - Topic detection.
   - Generated-file ignore rules.
   - Raw source hash capture.

3. **Manifest and invalidation**
   - SQLite manifest.
   - Source hash, generated hash, run, and config hash tracking.
   - No-op and config-change behavior.

4. **Schema renderer and atomic writer**
   - Markdown schemas.
   - Temp write + atomic rename.
   - Crash/retry convergence.

5. **Pipeline + refresh CLI**
   - Build topic bundle.
   - Fake summarizer integration.
   - Write summary/changelog.

6. **Watch mode**
   - Debounced topic refresh.
   - Per-topic event isolation.

7. **Local LLM adapter layer**
   - MLX adapter first if model format is available.
   - Ollama fallback adapter if MLX setup is blocked.
   - Keep llama.cpp adapter as post-v1 unless needed.

8. **Docs and model profiles**
   - README.
   - Runtime/model notes.
   - Non-goals and safety guarantees.

## Acceptance Criteria

1. Fake-adapter CI path can run all pipeline tests without any live LLM or model download.
2. `mindfresh refresh <fixture-vault>` creates `SUMMARY.md` and `CHANGELOG.md` for each topic with raw notes.
3. Adding a new local `.md` to one topic updates only that topic's generated files and manifest records.
4. Raw source Markdown files are byte-for-byte unchanged after refresh/watch.
5. Generated files are never included in source bundles, even if they contain Markdown and generated frontmatter.
6. A no-op refresh with unchanged sources/config preserves generated file hashes and does not append changelog noise.
7. Prompt schema changes trigger regeneration; model patch-version changes are recorded and only regenerate with `--force` unless configured otherwise.
8. `SUMMARY.md` contains current conclusion, recent changes, stable retained facts, stale/conflicting claims, open questions, and source references.
9. `CHANGELOG.md` contains trigger files, run ID/timestamp, summary delta, updated claims, stale/conflict notes, source path/hash references, and model/runtime profile.
10. Two independent topic folders refresh without cross-contaminating sources, summaries, changelogs, or manifest entries.
11. Watch mode detects a new local Markdown file and refreshes the affected topic after debounce.
12. Crash/retry simulation after generated write but before manifest update converges on next run without corrupting raw notes.
13. `mindfresh doctor` reports ignored generated files and active adapter/model profile.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Generated summaries get re-ingested | Hard exclusions, generated frontmatter, scanner tests, source-bundle assertions. |
| Raw files accidentally modified | Read-only source layer, before/after hash tests, no source write APIs. |
| Watch mode creates noisy churn | Debounce, manifest no-op detection, generated hash preservation checks. |
| LLM misses or hallucinates changes | Structured prompt/schema, source references, stale/conflict section, fake tests for pipeline, manual model smoke. |
| Direct update reduces trust | Detailed changelog with source references and run metadata; future rollback/review mode follow-up. |
| Large topics exceed context | Changed-files-first bundle, previous summary compression, future prompt caching/chunking work. |
| 26B/31B local runtime too slow | Fake/no-model path first, fast-mode model, Ollama fallback, benchmark-gated quality mode. |
| SQLite manifest complexity | Repository abstraction and migration-free initial schema; consider JSON export later. |
| Accidental watching of the wrong vault | Explicit vault registry, enabled flags, no home-directory autodiscovery, `watch --all-enabled` limited to enabled registered vaults, per-vault manifests. |
| Users avoid setup because config editing is annoying | First-run wizard, vault manager commands, status/doctor, optional menubar UI after core pipeline. |

## Out-of-scope Follow-ups

- Markdown note folder plugin.
- Web/RSS/source monitoring.
- Vector search/RAG.
- Review-draft workflow.
- Rollback command.
- llama.cpp adapter unless MLX/Ollama fail.
