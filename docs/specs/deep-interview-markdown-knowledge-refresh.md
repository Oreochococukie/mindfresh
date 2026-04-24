# Deep Interview Spec: Markdown Knowledge Refresh

## Metadata

- Interview ID: `3d516d61-b1e0-42d4-a7f8-bc8fdf7ef6f2`
- Created: 2026-04-24T07:30:25.029285+00:00
- Profile: Standard
- Context type: Greenfield
- Final ambiguity: **16%**
- Threshold: **20%**
- Rounds: 7
- Context snapshot: `.omx/context/markdown-knowledge-refresh-20260424T071810Z.md`
- Transcript: `.omx/interviews/markdown-knowledge-refresh-20260424T073025Z.md`
- Prompt-safe initial-context summary: not needed; initial prompt was within safe budget.

## Clarity Breakdown

| Dimension | Score | Status |
|---|---:|---|
| Intent Clarity | 0.90 | Freshness-first intent clarified. |
| Outcome Clarity | 0.90 | Per-topic `SUMMARY.md` + `CHANGELOG.md`. |
| Scope Clarity | 0.85 | Local Markdown watcher v1; no automatic web crawling. |
| Constraint Clarity | 0.80 | Local-first, source-preserving, developer laptop-friendly design. |
| Success Criteria Clarity | 0.80 | Core pass/fail checks identified; exact thresholds to define in plan/test spec. |

## Intent

사용자는 여러 빠르게 변하는 연구 주제를 병렬로 다루면서 “매번 새 자료를 다시 읽고 재검토해야 하는” 지식 최신화 부담을 줄이고 싶다. 이 프로젝트의 본질은 노트 앱을 새로 만드는 것이 아니라, 이미 쌓이는 Markdown 연구자료를 자동으로 압축·갱신해 **현재 믿을 수 있는 최신 상태**를 빠르게 회수하게 만드는 것이다.

v1의 최상위 원칙은 **최신성 우선(freshness-first)**이다.

- 1순위: 새 Markdown 노트가 들어왔을 때 기존 주제 요약이 최신 상태로 갱신된다.
- 2순위: 사용자가 원문 전체를 다시 읽지 않아도 핵심 변화와 현재 결론을 파악한다.
- 3순위: 무엇 때문에 요약이 바뀌었는지 근거와 변경 이유를 추적한다.

## Desired Outcome

사용자가 다음처럼 주제별 폴더를 유지한다.

```text
vault/
  research/
    topic-a/
      2026-04-24-source-a.md
      2026-04-24-source-b.md
      SUMMARY.md
      CHANGELOG.md
    topic-b/
      ...
  policy/
    policy-platform/
      ...
```

새로운 Markdown 파일이 topic folder에 추가되면, 시스템이 폴더를 감지하고 해당 폴더의 생성 파일을 즉시 갱신한다.

- `SUMMARY.md`: 현재 기준의 통합 요약/현재 결론/중요 판단.
- `CHANGELOG.md`: 새 노트 때문에 무엇이 바뀌었는지, 어떤 기존 주장이 낡았는지, 어떤 근거가 추가되었는지 기록.

원본 Markdown 파일은 절대 수정하지 않는다.

## In Scope — v1

1. 로컬 Markdown vault/folder 감시.
2. 주제 폴더에 새 `.md` 파일이 생기면 topic refresh 실행.
3. 각 topic folder의 원문 Markdown들을 읽고 통합 상태를 계산.
4. `SUMMARY.md` 갱신.
5. `CHANGELOG.md` 갱신.
6. 새 정보 반영, 변경 이유, 낡은/충돌 주장 표시.
7. 로컬 LLM 런타임 사용 가능.
8. 설계자가 요약 스키마, 로컬 LLM 런타임, 기술 스택을 선택 가능.
9. developer laptop에서 무리 없이 실행되는 27B/32B급 양자화 로컬 모델 후보를 우선 검토.
10. 원문 보존: source notes는 read-only 취급.

## Out of Scope / Non-goals — v1

1. 자동 웹/RSS/논문/GitHub/Research registry 크롤링 또는 수집.
2. 원본 Markdown 파일 수정.
3. 사용자의 명시적 요청 없이 원본 파일 삭제/이동/리네이밍.
4. 최신성 판단을 “웹 전체의 최신 정보”로 보장하는 것. v1의 최신성은 **사용자가 폴더에 추가한 Markdown 입력 기준**이다.

명시적으로 제외되지 않은 항목이지만 계획 단계에서 비용 대비 검토할 항목:

- Markdown note folder 플러그인화.
- 벡터DB/RAG 검색 기능.
- GUI/대시보드.
- 클라우드 LLM fallback.

## Decision Boundaries

### OMX/설계자가 확인 없이 결정해도 되는 것

- 요약 스키마: `SUMMARY.md`와 `CHANGELOG.md`의 섹션 구조, freshness marker, conflict marker, source citation 방식.
- 로컬 LLM 런타임: 예: Ollama, llama.cpp, LM Studio, MLX 계열 등 후보 평가 후 선택.
- 기술 스택: 예: Python/Node, SQLite/JSON manifest, watcher library, test fixtures 등.

### 이미 사용자 답변으로 확정된 것

- v1 최상위 원칙: **최신성 우선**.
- v1 산출물: **topic folder별 `SUMMARY.md` + `CHANGELOG.md`**.
- v1 실행 방식: **폴더 감시 + 즉시 갱신**.
- v1 review gate: 별도 승인 대기 초안이 아니라 생성 파일을 직접 갱신한다.
- source files: 원문 Markdown은 수정하지 않는다.

### 추가 확인이 필요한 경우

아래는 계획/실행 중 발견되면 사용자 확인 또는 명시적 plan decision이 필요하다.

- 유료/클라우드 API 호출이 필요한 경우.
- 모델 다운로드 용량이 매우 크거나 설정이 복잡한 경우.
- Markdown note folder plugin/GUI/외부 수집 등 v1을 넘어서는 범위 확장.
- 원문 파일 이동/삭제/이름 변경.

## Constraints

- Local-first design preferred.
- Hardware target: Apple developer laptop, common memory unified memory.
- Local LLM should be comfortable enough for repeated background refresh; exact model/runtime must be benchmarked or at least validated in planning.
- Keep maintenance burden low; the tool must not become another system the user has to babysit.
- Preserve folder hierarchy and compatibility with Markdown note folder-style Markdown workflows.
- Generated files must be distinguishable from user-authored raw notes.

## Testable Acceptance Criteria

Given a fixture vault:

```text
fixtures/vault/research/topic-a/
  2026-04-01-topic-a-baseline.md
  2026-04-20-topic-b-comparison.md
```

When a new file is added:

```text
2026-04-24-new-topic-a-node-findings.md
```

and the watcher refreshes the folder, then:

1. `SUMMARY.md` exists in the same topic folder.
2. `CHANGELOG.md` exists in the same topic folder.
3. `SUMMARY.md` includes the key new information from the newly added note.
4. `SUMMARY.md` updates or flags stale claims that conflict with the new note.
5. `CHANGELOG.md` records which input file(s) caused the change.
6. `CHANGELOG.md` includes timestamp or run identifier for the refresh.
7. Raw input Markdown files are byte-for-byte unchanged after refresh.
8. A user can read `SUMMARY.md` + latest `CHANGELOG.md` entry and understand the current topic state without rereading all raw notes.
9. The tool handles at least two independent topic folders without cross-contaminating summaries.
10. Re-running refresh without new input is idempotent or records no meaningless churn.

## Assumptions Exposed + Resolutions

### Assumption 1: “최신성, 압축, 근거 신뢰를 모두 v1에서 동등하게 보장해야 한다.”

- Pressure: equal priority would expand scope and blur architecture.
- Resolution: v1 is **freshness-first**. Compression and provenance are required insofar as they support freshness.

### Assumption 2: “자동으로 최신성을 유지하려면 웹까지 수집해야 한다.”

- Pressure: automatic web crawling would create source quality, rate limit, policy, and scope complexity.
- Resolution: v1 explicitly excludes automatic web collection. Freshness means “new user-added Markdown notes are integrated quickly.”

### Assumption 3: “자동 갱신은 review draft가 필요할 수도 있다.”

- Pressure: review draft lowers risk but increases friction and may preserve the knowledge freshness bottleneck.
- Resolution: user selected **watcher + direct update**. Generated summary files update immediately; raw source notes remain immutable.

## Pressure-pass Findings

Round 1 answer treated freshness, compression, and provenance as equally important. Round 2 forced the tradeoff: if v1 must not fail on one axis, choose the one. User selected freshness-first. This changed the design center from “knowledge management suite” to “freshness maintenance pipeline for topic summaries.”

## Technical Context Findings

- Current working directory is greenfield. `omx explore` found only `.omx` runtime/control artifacts and no source, build, package, README, or app files.
- No brownfield constraints exist yet.
- Recommended planning direction:
  - File watcher over vault root.
  - Topic folder detector: any folder containing raw `.md` files except generated files.
  - Generated-file ignore rules for `SUMMARY.md`, `CHANGELOG.md`, and hidden state/manifest files.
  - Incremental manifest to track input file hashes and refresh runs.
  - Local summarization adapter abstraction so runtime/model can be swapped.
  - Test fixture vaults for deterministic behavior.

## Evidence vs Inference Notes

### Evidence

- User explicitly wants Markdown hierarchy similar to Markdown note folder.
- User explicitly wants original summary/source files preserved and aggregate summary regenerated.
- User explicitly selected freshness-first.
- User explicitly excluded automatic web crawling for v1.
- User explicitly selected summary + changelog.
- User explicitly selected folder watcher + direct update.
- User allowed design decisions for summary schema, local LLM runtime, and tech stack.

### Inference

- The project should likely start as a local CLI/daemon rather than GUI/plugin because watcher-direct-update can be implemented and tested without UI.
- Local LLM should probably use a swappable adapter because model choice may change quickly.
- A manifest/hash layer is likely necessary to prevent useless regeneration and to prove raw-file immutability.

## Condensed Transcript

1. User described knowledge freshness bottleneck from parallel fast-changing research topics and proposed Markdown topic folders with refreshed summaries.
2. Asked which failure v1 must solve first; user said freshness, compression, and provenance are all important.
3. Forced tradeoff; user chose freshness-first.
4. Asked non-goals; user excluded automatic web crawling and added no other non-goals.
5. Asked decision boundaries; user allowed summary schema, local LLM runtime, and tech stack decisions.
6. Asked output form; user chose summary + changelog.
7. Asked success criteria; user said all listed checks are important.
8. Asked operational shape; user chose folder watcher + direct update.

## Recommended Handoff

Recommended next lane: **`$ralplan`**.

Reason: requirements are now clear enough to stop interviewing, but architecture/model/runtime/test-shape need explicit planning before implementation. Planning should produce:

- `.omx/plans/prd-*.md`
- `.omx/plans/test-spec-*.md`
- model/runtime decision notes
- v1 file structure and acceptance fixtures

Suggested invocation:

```text
$plan --consensus --direct .omx/specs/deep-interview-markdown-knowledge-refresh.md
```

Alternative handoffs:

- `$autopilot .omx/specs/deep-interview-markdown-knowledge-refresh.md` — use if direct plan+implementation is desired.
- `$ralph .omx/specs/deep-interview-markdown-knowledge-refresh.md` — use if a persistent single-owner completion loop is desired after planning artifacts exist.
- `$team .omx/specs/deep-interview-markdown-knowledge-refresh.md` — use if splitting lanes (watcher, summarizer, local LLM, tests, docs) becomes valuable.
- Refine further — use only if you want stronger decisions on Markdown note folder plugin, vector DB, GUI, or cloud fallback before planning.

## Residual Risk

Residual ambiguity is below threshold, but planning should still validate:

- local model/runtime feasibility on developer laptop;
- direct-update safety and rollback story for generated files;
- how to prevent generated summaries from being re-ingested as raw notes;
- exact schema for stale/conflict markers;
- deterministic tests despite LLM nondeterminism.
