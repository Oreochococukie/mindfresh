# Implementation Phases

This repo is implemented phase-by-phase. Each phase should end with:

1. relevant tests passing;
2. README/docs updated when behavior changes;
3. one Lore-style commit;
4. local branch pushed to the private GitHub remote;
5. `git status --short --branch` showing local and remote are aligned.

Current status: the implementation covers Phases 1–7 with deterministic fake-adapter tests, optional MLX/Ollama live adapters, and bounded `watch --once`. Phase 8 packaging/distribution polish remains.

## Phase 0 — Planning baseline

- Commit planning artifacts, README, and phase policy.
- Create private GitHub repository and push `main`.

## Phase 1 — Scaffold + no-manual-config UX

- Python project scaffold.
- CLI shell.
- `mindfresh init` wizard.
- `mindfresh vault add/list/enable/disable/remove/rename/status`.
- `mindfresh status` and `mindfresh doctor` stubs.
- Fake/no-model adapter path available for CI.

Acceptance:

- Users can create and mutate config without hand-editing files.
- Config writes are atomic.
- Only explicitly registered/enabled vaults are eligible for `watch --all-enabled`.

## Phase 2 — Scanner and source boundaries

- Topic folder detection.
- Generated file exclusions.
- Hidden/internal folder exclusions.
- SHA-256 source hashing.
- Raw file before/after immutability checks.

Acceptance:

- `SUMMARY.md`, `CHANGELOG.md`, and `mindfresh_generated: true` files are never source inputs.
- Multiple vaults and topics do not cross-contaminate.

## Phase 3 — Manifest and idempotence

- Per-vault `.mindfresh/manifest.sqlite`.
- Schema version `1`.
- Source/generation/config hash tracking.
- No-op refresh behavior.
- Prompt/model/config invalidation key.

Acceptance:

- Unchanged refresh preserves generated hashes and avoids changelog noise.
- Prompt schema changes trigger regeneration.
- Model patch changes are recorded unless forced.

## Phase 4 — Generated schemas and atomic writer

- `SUMMARY.md` template.
- `CHANGELOG.md` template.
- Same-directory temp write and atomic rename.
- Crash-window recovery tests.

Acceptance:

- Raw notes remain unchanged.
- Crash/retry converges without corrupting generated files or manifest.

## Phase 5 — Refresh pipeline with fake adapter

- Topic bundle creation.
- Fake summarizer.
- Freshness transition table implementation.
- Source-referenced summary/changelog rendering.

Acceptance:

- Fixture vault refresh passes without live LLM.
- Changed/conflict/stale-risk cases are covered deterministically.

## Phase 6 — Watch mode

- Recursive watcher for selected vaults only.
- Debounce per topic.
- Refresh affected topic only.
- `watch --all-enabled` respects enabled registry.

Acceptance:

- Disabled vaults are not watched.
- New note in one topic updates only that topic.

## Phase 7 — Local model adapters

- MLX adapter for local Apple Silicon model path.
- Ollama adapter fallback.
- Doctor checks for model availability.
- Manual smoke tests with local Gemma 4 31B.

Acceptance:

- Fake adapter remains default for CI.
- Live adapters are optional extras.
- Model/runtime dependencies are isolated behind adapter interfaces.
- Vault-level `adapter`/`model` settings are honored by `refresh` and `watch --all-enabled`.

## Phase 8 — Packaging and distribution

- Installation docs.
- Release checklist.
- Example vault.
- Optional macOS menubar app feasibility note.

Acceptance:

- A new user can install, run `mindfresh init`, add a vault, run fake refresh, and understand model setup without editing config manually.
