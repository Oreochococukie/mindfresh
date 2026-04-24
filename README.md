# mindfresh

Local-first Markdown freshness watcher for reducing research knowledge freshness bottlenecks.

`mindfresh` watches only the vaults you explicitly register and enable. When you add a new Markdown research note to a topic folder, it refreshes that topic's generated `SUMMARY.md` and `CHANGELOG.md` while leaving your original notes untouched.

> Status: planning complete. Implementation will proceed phase-by-phase with local and remote Git commits kept in sync.

## Why this exists

Fast-moving topics like Research models, research workflows, policy policies, and AI tooling change every day. A week-old note can already be stale. `mindfresh` is designed to keep topic-level summaries fresh without forcing you to reread every raw note.

## Core behavior

```text
vault/
  research/
    topic-a/
      2026-04-24-source-a.md    # raw note, never edited
      2026-04-25-source-b.md       # raw note, never edited
      SUMMARY.md                       # generated current state
      CHANGELOG.md                     # generated change history
  .mindfresh/
    manifest.sqlite                    # internal state for this vault only
```

Flow:

1. You register a vault explicitly.
2. You enable only the vaults you want watched.
3. `mindfresh watch --all-enabled` watches enabled registered vaults only.
4. New or changed raw `.md` files trigger a per-topic refresh.
5. Generated files are excluded from source ingestion to avoid self-summarizing loops.
6. Raw notes remain byte-for-byte unchanged.

## Planned user experience

First-run wizard:

```bash
mindfresh init
```

Vault management without editing config:

```bash
mindfresh vault add research ~/Documents/MindfreshDemoVault
mindfresh vault enable research
mindfresh vault disable archive
mindfresh vault list
mindfresh vault status research
```

Watching:

```bash
mindfresh watch research
mindfresh watch --all-enabled
```

One-off explicit path watch is allowed but does not auto-register the path:

```bash
mindfresh watch ~/Documents/MindfreshDemoVault
```

## Local model direction

The architecture keeps model/runtime behind adapters.

Planned adapters:

- `fake`: deterministic no-model adapter for tests and CI.
- `mlx`: primary local Apple Silicon adapter.
- `ollama`: fallback local-server adapter.
- `llama.cpp`: deferred unless needed.

The current preferred quality model is the user's existing local Gemma 4 31B model when performance is acceptable. The plan still keeps model availability capability-detected and adapter-based rather than hardcoded.

## Safety guarantees

- No automatic home/Desktop/Documents scanning.
- No automatic web/RSS/GitHub/paper crawling in v1.
- Only explicitly registered and enabled vaults are watched by `--all-enabled`.
- Each vault has its own `.mindfresh/manifest.sqlite`.
- Raw source notes are never modified, moved, renamed, or deleted.
- `SUMMARY.md` and `CHANGELOG.md` are generated files and are never re-ingested as raw sources.
- No-op refreshes should preserve generated hashes and avoid changelog noise.

## Implementation phases

See [`docs/operations/PHASES.md`](docs/operations/PHASES.md).

High-level phases:

1. Scaffold, `mindfresh init`, vault registry, status/doctor, fake adapter CI path.
2. Scanner, generated-file exclusions, source hashing, raw immutability.
3. Manifest, invalidation, no-op idempotence.
4. Summary/changelog schemas and atomic writer.
5. Refresh pipeline with fake adapter.
6. Watch mode with debounced per-topic refresh.
7. MLX/Ollama local model adapters.
8. Packaging and distribution docs.

## Planning artifacts

- [Deep interview spec](docs/specs/deep-interview-markdown-knowledge-refresh.md)
- [Consensus plan](docs/plans/ralplan-markdown-knowledge-refresh.md)
- [PRD](docs/plans/prd-markdown-knowledge-refresh.md)
- [Test spec](docs/plans/test-spec-markdown-knowledge-refresh.md)

## Development policy

Every phase should be committed separately and pushed to the private GitHub remote before moving to the next phase. Commit messages follow the project's Lore Commit Protocol with rationale, constraints, confidence, test evidence, and known gaps.
