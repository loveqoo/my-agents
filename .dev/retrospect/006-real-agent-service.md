# 006 — 실 에이전트 서비스 루프 회고 (Phase 1~3, 자율 진행)

날짜: 2026-06-23
지배 스펙: [docs/spec/007-real-agent-service.md](../../docs/spec/007-real-agent-service.md)
브랜치: `feat/agent-service` (main 머지 금지 — 사용자가 직접 테스트)

## 루프 개요
- **목표:** 어드민 UI(006, 전부 mock)가 기대하는 도메인을 실 백엔드 + 에이전트 런타임으로 구현. langchain/langgraph/mem0 사용.
- **위임 방식:** 사용자가 "6원칙 지키며 플랜·실행·검증·회고를 스스로 진행"하라고 위임 → 승인 대기 없이 self-drive. 단 플랜은 파일로, 검증은 타자(codex) 우선.
- **단계:**
  - 1 Scaffolding/Context — 브랜치 생성, 기존 백엔드(단일 agents 테이블) 정독
  - 3 Planning — `docs/spec/007` (자율 결정 기록)
  - 4 Execution
    - **Phase 1** 도메인 영속화: 관계형 모델(블록 5종·agents·versions·sessions·messages·approvals) + CRUD 라우터(리소스별 병렬 서브에이전트) + 시드(mock→DB)
    - **Phase 2** 런타임: build_agent(tools) + 합성 MCP 툴 + mem0(로컬 MLX) + 세션/메시지/트레이스 영속
    - **Phase 3** UI 배선: api.ts 전체 클라이언트 + 5뷰 병렬 서브에이전트로 실 API 연결
  - 5 Verification — 각 Phase API/채팅 스모크 + codex GATE(3회), 통합(tsc/build/서버 가동)
  - 6 Compounding — 본 회고 + 학습 009

## 무엇이 배웠나 / 잘못됐나
- **mem0 로컬 구성**이 가장 불확실했는데 실제로 돌았다 — 임베딩 전용 모델·`filters=` API·임베디드 qdrant. → [[009]]
- **스키마 교체 함정:** Agent 모델을 바꿨는데 `create_all`은 기존 테이블을 ALTER 안 함 → dev DB를 `DROP SCHEMA public CASCADE`로 재생성해야 했다. 다수 테이블 안정화 후 Alembic 필요.
- **codex가 잡은 실제 버그(타자 검증 가치):**
  - 버전 상태머신: fork 단일초안 가드 누락, 이미 active인 버전 재활성화 허용 (P1)
  - 세션이 agent로 스코프 안 됨 → 교차-에이전트 혼선 (P1)
  - 오류/부분 스트림을 성공 턴으로 영속·메모리 저장 (P2)
- **직렬화 계약 주의:** sessions/approvals의 `agentId`가 내부 UUID(외부 agt_ id와 불일치) — P2로 기록, UI가 매칭에 의존하면 보정.

## 잘된 것
- **기반 먼저 → 병렬 팬아웃**을 백엔드에도 적용: models/schemas/serializers를 직접 안정화한 뒤 라우터 3그룹을 병렬 서브에이전트로. Phase 3도 동일(api.ts → 5뷰 병렬).
- **단계별 커밋 + codex 게이트**로 큰 작업을 안전하게 분할. 각 Phase 끝-끝 스모크로 실제 동작 확인(특히 mem0 저장→회상).
- 자율 위임 하에서도 **플랜 파일·단계 표기·타자 검증** 원칙 유지.

## 다음에 / 추후
- Playground(agent-debug)를 실 `/agents/{id}/chat`(세션·트레이스)로 배선 — 현재는 mock agentData.
- AgentForm의 블록 옵션을 `/blocks`에서 로드(현재 정적 카탈로그).
- Alembic 마이그레이션, sessions/approvals agentId 외부 id화, mem0 재시도/멀티워커, 실 MCP 연결, HIL interrupt 실제화.

## 관련 기록
- [[009]] mem0 로컬 MLX 구성
- 이전 회고: [005-admin-console-and-playground-port](./005-admin-console-and-playground-port.md)
