# 028 — 플레이그라운드 모델 배지를 source별로 정직하게

상태: **실행·검증 완료(Execution/Verification) — main 머지 보류**(사용자 직접 브랜치 테스트 예정)
날짜: 2026-06-26
브랜치: `feat/agent-service` — **main 머지 금지**(사용자 직접 브랜치 테스트 예정)
연동: [025 playground proxy/override](./025-playground-proxy-config-override.md),
[026 external A2A 등록](./026-external-agent-a2a-card-registration.md),
[007 실 에이전트 서비스](./007-real-agent-service.md)
참고: `.dev/retrospect/018` · `.dev/learning/029`("증상이 아니라 결합을 끊어라")

## 배경 / 문제

사용자 보고: *"playground에서 'Doc Translator'의 모델은 qwen으로 되어 있는데 mock llm이
응답해. 수정 필요. 또한 다른 에이전트도 마찬가지."*

라이브 측정(override 없이 호출):

- **ui 에이전트 4개**(Research/Reviewer/Ops/Secretary) → **진짜 qwen** 스트리밍.
- **code 에이전트 1개**(Doc Translator, `source="code"`) → **mock 원격**
  (`endpoint=http://127.0.0.1:8000/_remote/agent`, dev mock). 이는 **설계대로**(스펙 025/007:
  code 에이전트는 로컬 모델을 안 쓰고 자기 원격 엔드포인트로 bypass).

**진짜 결함은 표시**다. `DebugChat.tsx`가 모델 배지(헤더·피커 두 곳)에서 `agent.model`을
**source와 무관하게** 실행 모델인 양 보여준다. code 에이전트는 `model` 필드가
`"qwen3.6-35b"`로 박혀 있지만(시드값) **그 모델로 돌지 않는다** → 배지가 거짓말.
external은 `model=""`라 빈 칸. 즉 **배지가 실행 주체(source)와 어긋난 결합**이 원인.

> [[029-same-origin-proxy-collapses-cross-origin-class]]의 원칙 적용: 증상(특정 에이전트)
> 하나가 아니라 **배지가 source를 무시하는 결합**을 끊는다.

## 결정 — 배지를 source별로 정직하게 (표시만, 로직 무변경)

`admin/src/playground/DebugChat.tsx` 한 파일. 헬퍼 하나로 두 표시 지점(헤더 칩·피커 행) 통일.

| source | 배지 | 색/스타일 | Tooltip |
|---|---|---|---|
| `ui` | `agent.model`(예 qwen3.6-35b) | primary(현행 유지) | — |
| `code` | **"코드 정의"** | 중립색(primary 아님 → 로컬 모델 아님을 시각 구분) | `runtime` + `endpoint`("원격 엔드포인트에서 실행 — 로컬 모델 미사용") |
| `external` | **"외부 A2A"** | 중립색 | 카드 URL(`endpoint`/`card.url`) |

- ui 배지는 **실행 모델이 맞으므로 그대로** 둔다.
- API가 `source`/`runtime`/`endpoint`/`repo`를 이미 내려줌(라이브 확인) — 추가 필드 불필요.
- **백엔드·chat.py 라우팅 무변경**(동작은 설계대로 정상). `OverridePanel`은 이미 정직
  ("코드 에이전트 — 오버라이드 미적용 … 원격 엔드포인트에서 실행")하므로 손대지 않는다.

## 변경 범위

- `admin/src/playground/DebugChat.tsx`
  - `AgentCombo` 헤더 칩(현 `{agent.model}`, ~148줄) → 헬퍼 경유.
  - 드롭다운 피커 행(현 `{a.model}`, ~233줄) → 헬퍼 경유.
  - 신규 헬퍼 `modelBadge(a: Agent)` → `{ text, primary, tooltip }`.

## 검증 (자가검증 지양)

1. `cd admin && npx tsc --noEmit` → 0 에러.
2. **서브에이전트/codex 비판적 리뷰** — 배지 로직이 세 source를 정확히 가르는지, OverridePanel과
   메시지 일관성, 회귀(ui 배지 그대로).
3. 브라우저: Doc Translator 선택 → 헤더·피커 모두 **"코드 정의"**(qwen 아님), Tooltip에 runtime/endpoint.
   ui 에이전트는 여전히 모델명. external 에이전트는 "외부 A2A".

## 완료 조건

- [x] DebugChat 배지가 source별로 정직(ui=모델 / code="코드 정의" / external="외부 A2A")
- [x] 헤더 칩·피커 행 두 곳 모두 `ModelBadge` 헬퍼 경유로 일관
- [x] `tsc --noEmit` 0 에러 + 서브에이전트 비판 리뷰 **PASS**(이슈 low/nit만)
- [x] 백엔드/라우팅 무변경(표시만 수정) — `DebugChat.tsx` 한 파일
- [x] 브라우저 직접 검증: Playwright+시스템 Chrome로 BEFORE(qwen)→AFTER("코드 정의") 캡처
- [ ] **main 머지 금지**

## 검증 자산

- `tests/browser/shot-playground.mjs` — 시스템 Chrome(`channel:'chrome'`)로 admin을 띄워
  Playground 메뉴 클릭→picker 펼침→스샷. 라우팅이 React state라 딥링크 불가해 클릭으로 진입.
  playwright는 npx 캐시에서 `PLAYWRIGHT_DIR` 절대경로 동적 import(ESM은 NODE_PATH 무시).
  실행: `PLAYWRIGHT_DIR=~/.npm/_npx/<hash>/node_modules/playwright node tests/browser/shot-playground.mjs out.png`
