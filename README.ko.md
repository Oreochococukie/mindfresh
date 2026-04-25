# mindfresh

[English](README.md) | 한국어

리서치 지식 최신화 부담을 줄이기 위한 로컬 우선 Markdown 최신화/중복 제거 watcher입니다.

`mindfresh`는 사용자가 명시적으로 등록하고 활성화한 vault만 감시합니다. 특정 주제 폴더에 새 Markdown 리서치 노트를 추가하면, 원본 노트는 건드리지 않고 해당 주제의 생성 파일인 `SUMMARY.md`와 `CHANGELOG.md`를 갱신합니다.

> 상태: Phase 7 어댑터 연결과 관리 UX slice까지 구현되어 있습니다. 현재 빌드는 명시적 vault 레지스트리, deterministic fake adapter, 선택적 Google Gemini / MLX / Ollama adapter, 모델 preset, guided setup/config migration, API-key presence diagnostics, actionable `doctor` remediation, topic scanner, manifest/idempotence tracking, generated latest-state/changelog writer, bounded `watch --once` flow를 포함합니다.

## 왜 만들었나

Research 모델, 콘텐츠 생성 워크플로, 정책 정책, AI 툴링처럼 빠르게 바뀌는 주제는 매일 새 정보가 나옵니다. 일주일 전에 정리한 노트도 금방 낡을 수 있습니다. `mindfresh`는 모든 원본 노트를 다시 읽지 않아도 주제별 지식을 최신 상태로 유지하기 위해 설계되었습니다.

생성되는 `SUMMARY.md`는 짧은 요약문이 아닙니다. 한국어 최신 상태 문서이며 다음을 목표로 합니다.

- 중요한 원문 컨텍스트, 날짜, 숫자, caveat, 비교를 보존합니다.
- 의미상 중복되는 claim을 하나의 canonical latest claim으로 병합합니다.
- 어떤 중복 claim이 접혔는지 기록합니다.
- 오래되었거나 충돌하는 claim을 조용히 삭제하지 않고 표시합니다.
- 원본 Markdown 노트는 그대로 둡니다.

## 핵심 동작

```text
vault/
  research/
    topic-a/
      2026-04-24-source-a.md    # 원본 노트, 수정하지 않음
      2026-04-25-source-b.md       # 원본 노트, 수정하지 않음
      SUMMARY.md                       # 생성된 최신 상태 + 중복 제거 문서
      CHANGELOG.md                     # 생성된 변경 이력
  .mindfresh/
    manifest.sqlite                    # 이 vault 전용 내부 상태
```

흐름:

1. vault를 명시적으로 등록합니다.
2. 감시할 vault만 활성화합니다.
3. `mindfresh watch --all-enabled`는 활성화된 등록 vault만 감시합니다.
4. 새 raw `.md` 파일이나 변경된 raw `.md` 파일이 있으면 주제별 refresh가 실행됩니다.
5. 생성 파일은 self-ingestion loop를 막기 위해 source ingestion에서 제외됩니다.
6. 원본 노트는 byte-for-byte로 유지됩니다.

## 빠른 시작 권장 경로

현재 private repo 기준으로는 먼저 clone한 뒤 local installer를 실행합니다. installer는 `sudo`, shell profile 자동 수정, background daemon 없이 사용자 소유 경로인 `~/.mindfresh`에 설치합니다.

```bash
git clone https://github.com/Oreochococukie/mindfresh.git
cd mindfresh
./install.sh
export PATH="$HOME/.mindfresh/bin:$PATH"
```

그다음 beginner-friendly onboarding을 실행합니다.

```bash
mindfresh onboard
```

`onboard`는 정확한 vault 폴더 경로를 붙여넣으라고 요청합니다. `mindfresh`는 home, Desktop, Documents, Markdown note folder 폴더를 자동 검색하지 않습니다. API key 값도 Mindfresh에 직접 입력하지 않습니다.

복붙 가능한 non-interactive onboarding도 지원합니다.

```bash
mindfresh onboard \
  --vault-name research \
  --vault-path ~/Documents/MindfreshDemoVault \
  --model-preset gemini-3-flash \
  --non-interactive
```

기본 preset은 `gemini-3-flash`이며 Google Gemini API 모델 `gemini-3-flash-preview`를 사용합니다. 실제 live 사용 전에는 API key 환경변수 하나를 설정하세요.

```bash
export GOOGLE_API_KEY="your-google-api-key"
# GEMINI_API_KEY도 사용할 수 있습니다.
mindfresh keys status
```

설치와 non-secret config 상태를 확인합니다.

```bash
mindfresh --version
mindfresh keys status
mindfresh models list
mindfresh doctor research
```

live model 없이 안전한 deterministic smoke를 실행합니다.

```bash
mindfresh refresh research --adapter fake
```

API key 설정 후 bounded live refresh/watch를 한 번 실행합니다.

```bash
mindfresh refresh research
mindfresh watch --all-enabled --once
```

### 개발자 수동 설치

repo 기여나 packaging 동작 디버깅 시 이 경로를 사용하세요.

```bash
git clone https://github.com/Oreochococukie/mindfresh.git
cd mindfresh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
mindfresh onboard
```

### 업데이트

기존 checkout에서:

```bash
cd mindfresh
git pull
./install.sh --prefix ~/.mindfresh --no-onboard
mindfresh --version
```

### 다른 Mac으로 non-secret config 옮기기

```bash
mindfresh config export --output mindfresh-config.json
# mindfresh-config.json을 다른 Mac으로 복사
mindfresh config import mindfresh-config.json
```

export에는 API key 값이 포함되지 않습니다. import할 때 대상 Mac에 존재하지 않는 vault path는 disabled 상태로 들어오며, 사용자가 명시적으로 수정/재활성화해야 합니다.

### 삭제

로컬 앱 설치 prefix를 삭제합니다. vault 노트는 삭제하지 않습니다.

```bash
rm -rf ~/.mindfresh
```

Mindfresh config까지 지우고 싶다면 선택적으로 실행합니다.

```bash
rm -rf ~/.config/mindfresh
```

빠른 troubleshooting:

```bash
~/.mindfresh/bin/mindfresh --version
export PATH="$HOME/.mindfresh/bin:$PATH"
mindfresh keys help
mindfresh doctor <vault-name>
```

## Vault 관리 UX

Vault 관리는 config 파일을 직접 편집하지 않아도 됩니다.

```bash
mindfresh setup --vault-name research --vault-path ~/Documents/MindfreshDemoVault --model-preset gemini-3-flash
mindfresh config show --json
mindfresh config export --output mindfresh-config.json
mindfresh config import mindfresh-config.json
mindfresh vault add research ~/Documents/MindfreshDemoVault
mindfresh vault model research gemini-3-flash
mindfresh vault enable research
mindfresh vault disable archive
mindfresh vault list
mindfresh vault status research
mindfresh keys status
mindfresh keys help
```

Model preset 관리:

```bash
mindfresh models list
mindfresh models set-default gemini-3-flash
mindfresh vault model research qwen3-14b-ollama
```

`mindfresh models list`는 "Recommended for this Mac" 안내도 출력합니다.

- 다른 Mac / 로컬 LLM 없음 → `gemini-3-flash` 기본 Gemini API 경로
- offline smaller local → `qwen3-14b-ollama` 또는 `gemma3-12b-ollama`
- offline quality local → `gemma4-31b-ollama`
- tests/CI → `fake`

Watching:

```bash
mindfresh watch research --once
mindfresh watch --all-enabled --once
```

명시적 path를 한 번 watch하는 것도 가능하지만, path를 자동 등록하지는 않습니다.

```bash
mindfresh watch ~/Documents/MindfreshDemoVault --once
```

장기 실행 watcher daemon은 의도적으로 deferred 상태입니다. 현재 slice는 background scheduling을 추가하기 전에 refresh contract를 안전하게 테스트할 수 있도록 `--once`를 제공합니다.

## 모델 방향

아키텍처는 model/runtime을 adapter 뒤에 둡니다.

구현된 adapter:

- `fake`: 테스트/CI용 deterministic no-model adapter.
- `google` / `gemini`: Google Gemini API adapter. 기본 model preset은 `gemini-3-flash`.
- `mlx`: `mlx_lm.generate` command를 통한 선택적 Apple Silicon adapter.
- `ollama`: Ollama `/api/generate` endpoint를 통한 선택적 local-server adapter.

Deferred adapter:

- `llama.cpp`: 필요해질 때까지 deferred.

기본 live preset은 `gemini-3-flash` (`google` adapter, `gemini-3-flash-preview` model)입니다. 따라서 큰 local LLM이 없는 다른 PC에서도 사용할 수 있습니다. offline/high-privacy 사용에는 Ollama 또는 MLX preset을 선택하세요.

### Google Gemini API

API key 설정:

```bash
export GOOGLE_API_KEY="your-google-api-key"
# 또는:
export GEMINI_API_KEY="your-google-api-key"
mindfresh keys status
```

`mindfresh keys status`는 presence/absence와 허용되는 변수명만 출력합니다. `mindfresh keys help`는 복붙 가능한 설정 명령을 출력합니다. 두 명령 모두 실제 API key 값은 출력하지 않습니다.

기본 preset 사용:

```bash
mindfresh setup --vault-name docs --vault-path ~/Documents/vault --model-preset gemini-3-flash
mindfresh doctor docs
mindfresh refresh docs
```

Google API host 기본값은 `https://generativelanguage.googleapis.com/v1beta`입니다. 테스트나 proxy가 필요한 경우에만 override하세요.

```bash
export MINDFRESH_GOOGLE_API_HOST="https://generativelanguage.googleapis.com/v1beta"
```

### 작은/로컬 컴퓨터용 preset

선택지를 확인합니다.

```bash
mindfresh models list
```

Built-in preset:

- `gemini-3-flash` — 기본 cloud model, local VRAM 필요 없음.
- `qwen3-14b-ollama` — 작은 local Ollama preset.
- `gemma3-12b-ollama` — 작은 local Ollama preset.
- `gemma4-31b-ollama` — 큰 local Ollama preset.
- `fake` — deterministic tests/CI.

### MLX로 Gemma 4 31B 사용

로컬 모델이 MLX-compatible model path라면 vault에 model path를 등록합니다.

```bash
mindfresh vault add research ~/Documents/MindfreshDemoVault \
  --adapter mlx \
  --model /path/to/your/gemma-4-31b-mlx-model

mindfresh refresh research
```

`mindfresh`는 기본적으로 `mlx_lm.generate`를 호출합니다. command가 다르면 다음처럼 설정하세요.

```bash
export MINDFRESH_MLX_COMMAND="python3 -m mlx_lm.generate"
mindfresh refresh research
```

### Ollama로 Gemma 4 31B 사용

모델이 Ollama에서 serve되고 있다면 Ollama model id를 사용합니다.

```bash
mindfresh vault add research ~/Documents/MindfreshDemoVault \
  --adapter ollama \
  --model your-gemma-4-31b-model-id

mindfresh refresh research
```

`mindfresh`는 기본적으로 `http://localhost:11434`를 사용합니다. 필요하면 override하세요.

```bash
export MINDFRESH_OLLAMA_HOST="http://127.0.0.1:11434"
mindfresh refresh research
```

Per-run override도 지원합니다.

```bash
mindfresh refresh research --model-preset gemini-3-flash
mindfresh refresh research --model-preset qwen3-14b-ollama
mindfresh refresh research --adapter mlx --model /path/to/model
mindfresh watch --all-enabled --once --adapter ollama --model your-model-id
```

Runtime diagnostics는 `doctor`에서 확인합니다.

```bash
mindfresh doctor research
```

Google의 경우 `doctor`는 `GOOGLE_API_KEY` 또는 `GEMINI_API_KEY`가 설정되어 있는지 확인합니다. Ollama의 경우 `/api/tags`로 configured model이 설치되어 있는지 확인합니다. MLX의 경우 command resolve 가능 여부와 local-looking model path 존재 여부를 확인합니다.

Diagnostics가 실패하면 `doctor`는 traceback 대신 actionable next step을 출력합니다.

- Google/Gemini: 허용 env var 이름, `export GOOGLE_API_KEY="your-google-api-key"`, `mindfresh keys status`, retry command.
- Ollama: Ollama 시작 또는 `MINDFRESH_OLLAMA_HOST` 설정, configured model을 `ollama pull ...`로 설치, 또는 더 작은 preset으로 전환.
- MLX: `mlx-lm` 설치/설정, `MINDFRESH_MLX_COMMAND` 설정, 또는 vault/run에 존재하는 local model path 지정.

`doctor`는 secret에 대해 presence-only입니다. 변수명은 언급할 수 있지만 API key 값은 절대 출력하지 않습니다.

## 안전 보장

- home/Desktop/Documents 자동 스캔 없음.
- v1에서는 web/RSS/GitHub/paper 자동 crawl 없음.
- `setup`은 명시적 `--vault-path` 입력에서만 vault를 기록합니다.
- `config export`는 non-secret입니다. API key는 각 machine에 남습니다.
- `keys status`, `keys help`, `doctor`는 API-key 값을 echo하지 않습니다.
- `config import`는 대상 Mac에 path가 없는 imported vault를 disabled 처리합니다.
- `--all-enabled`는 명시적으로 등록되고 활성화된 vault만 감시합니다.
- 각 vault는 자기 전용 `.mindfresh/manifest.sqlite`를 가집니다.
- 원본 source note는 수정, 이동, rename, 삭제하지 않습니다.
- `SUMMARY.md`와 `CHANGELOG.md`는 generated file이며 raw source로 재섭취하지 않습니다.
- `SUMMARY.md`는 손실이 큰 짧은 요약이 아니라 latest-state/dedupe artifact입니다.
- no-op refresh는 generated hash를 유지하고 changelog noise를 피해야 합니다.

## 구현 단계

[`docs/operations/PHASES.md`](docs/operations/PHASES.md)를 참고하세요.

상위 phase:

1. Scaffold, `mindfresh init`, vault registry, status/doctor, fake adapter CI path.
2. Scanner, generated-file exclusions, source hashing, raw immutability.
3. Manifest, invalidation, no-op idempotence.
4. Latest-state/changelog schema와 atomic writer.
5. Fake adapter 기반 refresh pipeline.
6. Debounced per-topic refresh를 포함한 watch mode.
7. Google Gemini / MLX / Ollama model adapter.
8. Packaging and distribution docs.

## 테스트와 검증

Deterministic test가 local-first pipeline의 release gate입니다.

```bash
python3 -m pytest -q
```

Test suite는 config/vault UX, scanner boundary, generated-never-reingested behavior, raw-note immutability, manifest/idempotence contract, watch debounce contract, crash/retry expectation, mocked live-adapter request/command boundary를 다룹니다. Coverage map과 focused command는 [Testing and Verification](docs/operations/TESTING.md)를 참고하세요.

## 계획 산출물

- [Deep interview spec](docs/specs/deep-interview-markdown-knowledge-refresh.md)
- [Consensus plan](docs/plans/ralplan-markdown-knowledge-refresh.md)
- [PRD](docs/plans/prd-markdown-knowledge-refresh.md)
- [Test spec](docs/plans/test-spec-markdown-knowledge-refresh.md)

## 개발 정책

각 phase는 다음 phase로 넘어가기 전에 별도 commit으로 만들고 private GitHub remote에 push해야 합니다. Commit message는 rationale, constraint, confidence, test evidence, known gap을 포함하는 프로젝트 Lore Commit Protocol을 따릅니다.
