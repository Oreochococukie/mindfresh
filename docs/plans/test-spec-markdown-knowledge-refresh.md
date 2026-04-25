# Test Spec: Markdown Knowledge Refresh (`mindfresh` v1)

## Scope

This test spec validates the local-only freshness watcher described in `docs/plans/prd-markdown-knowledge-refresh.md`.

## Test Fixtures

```text
fixtures/vault/
  research/
    model-evaluations/
      2026-04-01-baseline.md
      2026-04-20-comparison.md
    tooling-updates/
      2026-04-10-baseline.md
  policy/
    compliance/
      2026-04-01-policy.md
```

Generated files must be created during tests, not committed as raw sources unless under expected-output fixtures.

## Required Test Modes

1. **Fake adapter mode** — required for CI and all deterministic tests.
2. **Optional real model smoke** — manual/local only; not required for CI.

## Unit Tests

### No-manual-config UX

- `mindfresh init` can create a valid config through prompts without manual file editing.
- `mindfresh vault add/list/enable/disable/remove/rename/status` can mutate and display config safely.
- Invalid vault paths are rejected before saving.
- Config writes are atomic; interrupted write does not corrupt existing config.
- `mindfresh status` displays enabled vaults, disabled vaults, active watchers, last refresh, and errors.
- Docs present config file editing as optional advanced usage, not primary onboarding.

### Multi-vault registry

- `vault add <name> <path>` stores an explicit vault path and enabled status.
- `vault disable <name>` prevents `watch --all-enabled` from watching that vault.
- `watch <name>` resolves only registered vault names.
- `watch --all-enabled` watches enabled registered vaults only.
- The tool never auto-discovers arbitrary home/Desktop/Documents folders as vaults.
- Each registered vault uses its own `<vault>/.mindfresh/manifest.sqlite`.
- Two enabled vaults with similar topic paths do not share manifest rows or generated outputs.

### Scanner

- Detects topic folder when directory contains raw `.md` files.
- Ignores `SUMMARY.md`.
- Ignores `CHANGELOG.md`.
- Ignores `.mindfresh/**`.
- Ignores dot directories.
- Ignores `_generated/**` and `_review/**`.
- Ignores markdown with frontmatter `mindfresh_generated: true`.
- Returns source bundle paths relative to vault root.
- Does not cross topic boundaries.

### Hashing and raw immutability

- Computes SHA-256 for raw source files.
- Captures before/after hashes around a refresh.
- Fails if any source hash changes.

### Manifest

- Initializes schema version `1`.
- Records hash algorithm `sha256`.
- Inserts first-run source records.
- Detects new source file.
- Detects modified source hash.
- Detects no-op unchanged source/config.
- Tracks generated file hashes before/after.
- Tracks config/prompt/model profile hash.
- Regenerates on prompt schema hash change.
- Records model patch-version changes without forced regeneration by default.

### Freshness semantics

- Validates the PRD freshness transition table for first refresh, no-op, changed, conflicts, stale-risk, and resolved conflict cases.
- Marks recent info when source hash is new/changed since last run.
- Includes conflict marker when fake adapter reports contradiction.
- Retains stable facts when fake adapter marks them supported.
- Marks stale-risk when fake adapter reports unresolved old claim.

### Writer / atomicity

- Covers each crash window: before temp write, after temp write before rename, after rename before hash capture, after hash capture before manifest update.
- Writes temp file in target directory.
- Renames atomically to `SUMMARY.md`/`CHANGELOG.md`.
- Updates manifest only after generated hashes are known.
- Crash simulation before manifest update is recoverable on next refresh.
- No partial generated file remains after successful write.

### Schema rendering

- `SUMMARY.md` contains generated frontmatter and all required sections.
- `CHANGELOG.md` contains generated frontmatter and run entry fields.
- Source references include path and hash prefix.

## Integration Tests

### Initial refresh

Given fixture vault with raw notes only, when `mindfresh refresh fixtures/vault --adapter fake` runs:

- `SUMMARY.md` and `CHANGELOG.md` are created in each topic folder.
- `.mindfresh/manifest.sqlite` exists.
- Raw files are unchanged.
- Generated files are tagged with `mindfresh_generated: true`.

### Incremental single-topic refresh

Given an initialized fixture vault, when a new raw note is added to `research/model-evaluations/` and refresh runs:

- only `research/model-evaluations/SUMMARY.md`, `research/model-evaluations/CHANGELOG.md`, and manifest state change;
- `research/tooling-updates` and `policy/compliance` generated files remain unchanged;
- changelog entry lists the new note as trigger.

### No-op idempotence

Given no source/config changes, a second refresh:

- preserves `SUMMARY.md` hash;
- preserves `CHANGELOG.md` hash;
- does not add a changelog entry;
- records no new run or records a no-op run without touching generated files, depending on implementation decision.

### Generated-never-reingested

Given generated files exist and include rich Markdown content, source scanner excludes them from subsequent topic bundles.

### Watch mode

Using temp fixture vaults:

- register `vault_a` enabled and `vault_b` disabled;
- run `watch --all-enabled`;
- add a note under both vaults;
- assert only `vault_a` refreshes;
- enable `vault_b` and assert it refreshes only after explicit enable/watch.

Using a temp fixture vault:

- start watcher with low debounce;
- add one new `.md` file to `research/model-evaluations/`;
- assert refresh occurs for `research/model-evaluations` only;
- assert generated outputs update within bounded timeout.

### Crash/retry

Simulate crash after generated file write and before manifest update:

- next refresh detects mismatch;
- converges to a valid manifest/generated state;
- raw source files remain unchanged.

## Manual Smoke Tests

### MLX adapter smoke

- Install optional MLX dependencies.
- Configure a small/fast model first.
- Run `mindfresh refresh fixtures/vault --adapter mlx --topic research/model-evaluations`.
- Record latency, memory warnings, generated sections, and source references.

### Model profile comparison

Benchmark on one representative topic folder:

- fast mode model;
- Gemma 4 26B A4B profile if available;
- Gemma 4 31B profile only if feasible.

Pass condition for making 31B default: at least one severity-level improvement in human-rated stale/conflict detection or materially fewer missed-change cases, without exceeding the operator-accepted latency/memory budget. Otherwise 26B A4B remains quality default and 31B remains quality mode. Gemma 4 26B A4B availability must be detected by setup/doctor rather than assumed.

## Verification Commands

Target commands after implementation:

```bash
python -m pytest
mindfresh refresh fixtures/vault --adapter fake
mindfresh doctor fixtures/vault
```

Optional local model smoke:

```bash
mindfresh refresh fixtures/vault --adapter mlx --topic research/model-evaluations
mindfresh refresh fixtures/vault --adapter ollama --topic research/model-evaluations
```
