# RALPLAN Consensus Plan: Markdown Knowledge Refresh

## Status

- Source spec: `docs/specs/deep-interview-markdown-knowledge-refresh.md`
- PRD: `docs/plans/prd-markdown-knowledge-refresh.md`
- Test spec: `docs/plans/test-spec-markdown-knowledge-refresh.md`
- Mode: RALPLAN-DR short
- Current verdict: revised after Architect APPROVE-with-refinements and Critic ITERATE feedback.

## RALPLAN-DR Summary

### Principles

1. Freshness-first.
2. Raw source immutability.
3. Low operational overhead.
4. Local-first inference behind swappable adapter boundary.
5. Deterministic, testable pipeline around probabilistic LLM output.

### Decision Drivers

1. Direct-update safety and generated/source boundaries.
2. Apple Silicon common developer desktops/laptops practicality.
3. Testability without live model dependency.

### Options

1. **Python CLI/daemon + MLX-first adapter + SQLite manifest — chosen.** Best fit for MLX Python API, fake adapter tests, and deterministic pipeline.
2. **Node watcher + Ollama adapter.** Simpler HTTP/server path but weaker MLX-native control and service lifecycle dependency.
3. **editor plugin first.** Good UX but too much v1 scope before core pipeline is proven.

## Final Architecture Decision

Build `mindfresh` as a Python local-first CLI/daemon with:

- no-manual-config onboarding UX (`init`, vault manager, status/doctor);
- explicit multi-vault allowlist/registry;
- deterministic scanner;
- generated-file ignore rules;
- SQLite manifest;
- fake/no-model adapter first;
- MLX/`mlx-lm` adapter as default live local path;
- Ollama fallback;
- llama.cpp adapter deferred unless MLX/Ollama fail;
- atomic writer for generated `SUMMARY.md` and `CHANGELOG.md`.

## ADR

### Decision

Use Python + deterministic manifest pipeline + swappable summarizer adapters. Default live runtime target is MLX/`mlx-lm`; default quality model target is Gemma 4 26B A4B quantized for MLX if available. Gemma 4 31B is benchmark-gated quality mode, not v1 default.

### Drivers

- Freshness-first local Markdown updates.
- Raw-source immutability with direct generated-file writes.
- common developer desktops/laptops local feasibility.
- CI/testability without model downloads.
- Future model/runtime volatility.

### Alternatives considered

- Node + Ollama-first: viable fallback, not selected due to less MLX-native control and service dependency.
- editor plugin first: deferred due to UI/plugin complexity.
- 31B default: rejected until benchmark proves quality gain justifies memory/latency cost.
- Web/RSS ingestion: explicitly out of v1 scope.

### Why chosen

The selected architecture maximizes trust in freshness mechanics before optimizing model quality. It keeps all high-risk invariants testable with a fake adapter, then layers local LLM quality behind a replaceable boundary.

### Consequences

- v1 is CLI/watch based, not editor-native.
- MLX model setup may need validation during execution.
- Summary quality requires manual smoke tests in addition to deterministic CI.

### Follow-ups

- Benchmark 26B A4B vs 31B vs fast profile.
- Consider rollback/review mode if direct updates feel risky.
- Consider editor plugin after core pipeline stabilizes.
- Consider automatic web/source ingestion only after local-note freshness is proven.

## Implementation Plan

1. Scaffold Python project, `mindfresh init`, vault registry/allowlist, status/doctor UX, and fake/no-model CI path.
2. Implement scanner and generated-source boundary tests.
3. Implement manifest, invalidation, no-op behavior.
4. Implement schemas, freshness semantics, and atomic writer.
5. Implement refresh pipeline with fake adapter.
6. Implement watch mode with debounce and topic isolation.
7. Add MLX adapter; add Ollama fallback if MLX setup blocks.
8. Add docs, model runtime notes, and manual smoke instructions.

## Consensus Improvements Applied

- Fake/no-model mode elevated to first milestone and CI requirement.
- Explicit invariants added: generated never re-ingested, raw never modified, no-op preserves generated hashes, config changes are handled.
- Freshness semantics defined: recent, changed, conflict, stale-risk, stable retained.
- Atomicity protocol defined: temp write, atomic rename, hash capture, manifest after write, crash/retry tolerance.
- Model policy locked: Gemma 4 26B A4B default target, 31B benchmark-gated, smaller fast mode, Ollama fallback, llama.cpp deferred.
- Verification strengthened with concrete scanner, manifest, changelog, multi-topic, watch, and crash-safe retry assertions.
- Final critic improvements merged: freshness transition table, schema version/hash algorithm, explicit invalidation key, capability-detected Gemma profile, 31B benchmark gate, and crash-window tests.
- Requirement merged: multi-vault registry/allowlist so only explicitly selected vaults are watched; each vault keeps its own manifest.
- Requirement merged: distribution UX must not require hand-editing config; provide first-run wizard, vault manager commands, status/doctor, and later optional menubar/local UI.

## Available Agent Types Roster

- `explore`: repo lookup and file/symbol mapping.
- `planner`: sequencing and plan updates.
- `architect`: architecture review and tradeoffs.
- `critic`: plan/design challenge.
- `executor`: implementation/refactor work.
- `test-engineer`: fixture strategy and coverage.
- `dependency-expert`: local LLM/runtime evaluation.
- `verifier`: completion evidence and validation.
- `writer`: documentation and setup guide.
- `code-reviewer`: final comprehensive review.

## `$ralph` Follow-up Staffing Guidance

Use `$ralph docs/plans/ralplan-markdown-knowledge-refresh.md` for sequential execution.

Suggested sequence:

1. `executor` — scaffold and CLI.
2. `executor` — scanner/manifest/writer/pipeline.
3. `test-engineer` — fixture tests and crash/idempotence coverage.
4. `dependency-expert` — MLX/Ollama adapter validation.
5. `writer` — README/model runtime docs.
6. `verifier` — final PRD/test-spec acceptance pass.

Suggested reasoning: medium for implementation lanes, high for dependency/runtime validation, high for final verification.

## `$team` Follow-up Staffing Guidance

Use `$team docs/plans/ralplan-markdown-knowledge-refresh.md` when parallel execution is desired.

Suggested lanes:

1. `executor`: scaffold, config, CLI.
2. `executor`: scanner, ignore rules, source immutability.
3. `executor`: manifest, invalidation, atomic writer.
4. `executor`: summarizer protocol, fake adapter, prompt/schema.
5. `test-engineer`: fixture suite, watch/idempotence/crash tests.
6. `dependency-expert`: MLX/Ollama model/runtime validation.
7. `writer`: README and docs.
8. `verifier`: final evidence consolidation.

Launch hints:

```text
$team docs/plans/ralplan-markdown-knowledge-refresh.md
```

or CLI-style:

```bash
omx team "docs/plans/ralplan-markdown-knowledge-refresh.md"
```

Team verification path:

1. All fake-adapter unit/integration tests pass.
2. Fixture vault demonstrates raw immutability and generated-file exclusion.
3. Watch mode refreshes one topic only.
4. No-op refresh preserves generated hashes and avoids changelog churn.
5. Crash/retry simulation converges.
6. Docs explain v1 non-goals and model runtime policy.
7. Final `verifier` maps evidence back to PRD and test spec.
