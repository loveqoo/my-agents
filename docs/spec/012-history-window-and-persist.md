# 012 — 대화 히스토리: 실행 윈도우(historyDepth) + 저장 정책(persistHistory)

상태: **실행 중 (자율)**
날짜: 2026-06-23
브랜치: `feat/agent-service` — main 머지 금지
연동: [007 런타임](./007-real-agent-service.md), [008 모델](./008-model-registry.md)

> 두 관심사를 분리해 에이전트별 설정으로:
> 1) **실행 컨텍스트 윈도우** = `historyDepth`(최근 N개만 모델에 전달) — 지금은 미사용(죽은 설정).
> 2) **영속 정책** = `persistHistory`(대화를 DB에 저장할지) — 관측/재개 ↔ 저장량/프라이버시 트레이드오프.

## 1. 목표
- `historyDepth`를 실행에 적용: 모델에 보낼 메시지를 **최근 N개로 절단**. `0`이면 현재 턴만(과거 미기억).
- `persistHistory`(기본 true) 추가:
  - **true(저장)**: 매 턴 user/assistant(+트레이스) DB 저장. (현행)
  - **false(윈도우)**: 메시지 미저장. **세션 카운터(turns/tokens)만** 갱신. 라이브 인스펙터는 스트리밍으로 계속 동작(사후 기록만 없음).
- 둘 다 로컬·원격(코드 에이전트) 경로 공통 적용.
- 트레이스에 `contextMessages`(모델에 넣은 메시지 수) 추가 → 인스펙터 가시화 + 검증 가능.

## 2. 비범위
- 토큰 기반 윈도우(메시지 수가 아닌 토큰 예산) — 추후. 지금은 메시지 개수.
- 요약 기반 압축(rolling summary) — 추후.

## 3. 설계
- `AgentConfig.persistHistory: bool = True` (에이전트 `config` jsonb → 마이그레이션 불필요). `AgentOut`에도 노출.
- `chat.py`: `_window(messages, depth)`로 절단(0이면 `[-1:]`, 음수/None이면 전체; `[-0:]`=전체 함정 처리). `_persist(..., store_messages)`로 메시지 저장 여부 제어(카운터는 항상).
- UI `AgentForm`: "채팅 히스토리"(historyDepth) 옆에 "대화 저장"(persistHistory) 토글.

## 4. 검증 (결과)
- [x] historyDepth로 컨텍스트 절단 — E2E: depth=2 → `trace.contextMessages == 2`. 로컬·원격 공통.
- [x] persistHistory=false → 세션 메시지 0, `turns` 갱신(카운터만).
- [x] persistHistory=true(기본) 현행 유지. UI 토글 동작. 전체 E2E 29 passed.
- [x] codex GATE — P1/P2 0건. (`_window` 0/1/대량/음수 경계 검증됨.)

## 5. 추후 / 알려진 고려
- 토큰 예산 기반 윈도우·요약 압축(rolling summary).
- **user-first 정규화(codex 노트)**: historyDepth가 홀수면 윈도우가 assistant로 시작 가능. 현재 MLX는 허용하나, 첫 비-시스템 메시지로 user를 요구하는 엄격한 모델을 추가하면 선두 assistant 제거 규칙 필요.
