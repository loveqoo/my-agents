# 007 — 에이전트 서비스 확장 회고 (견고화·E2E·모델 레지스트리·원격 실행·env 일원화)

날짜: 2026-06-23
브랜치: `feat/agent-service` (main 머지 금지 — 사용자가 직접 테스트)
지배 스펙: [007](../../docs/spec/007-real-agent-service.md), [008](../../docs/spec/008-model-registry.md), [009](../../docs/spec/009-code-agent-remote-exec.md)
이전 회고: [006-real-agent-service](./006-real-agent-service.md)

## 루프 개요 (006 이후 연속 증분, 모두 자율)
1. **견고화 배치** — Alembic 도입(create_all 대체, async 이벤트루프 함정 해결), AgentForm 블록옵션 `/blocks` API화, sessions/approvals `agentId` 외부 id화, **단순(페르소나만) 에이전트 생성→대화 보장**.
2. **E2E 자동화** — Playwright(API 12 + 브라우저 9). **숨은 버그 발견**: 의미론적 메모리 켠 에이전트가 system 메시지 충돌로 전부 깨져 있던 것.
3. **Playground 실 배선** — mock agentData/HIL/A2UI 제거 → 실 에이전트 + `streamChat` + 실 트레이스 인스펙터.
4. **모델 레지스트리(008)** — LLM/임베딩 설정 등록(CRUD), 시드(qwen·e5), 에이전트가 고른 모델로 실행.
5. **코드 에이전트 원격 실행(009)** — `/chat`이 코드 에이전트면 등록 엔드포인트로 httpx 프록시(mock 원격 더블).
6. **env 일원화** — 런타임에서 MLX_* 폴백 제거, 모델 레지스트리만 봄.

## 무엇이 잘됐나
- **E2E가 회귀망이자 발견 도구**: 단발 스모크로 못 잡은 memory system-message 버그를 "저장→회상→영속" 시나리오가 포착([[010]]). 이후 모든 루프를 26~27 테스트로 검증.
- **타자 검증(codex) 매 루프**: 실제 P1을 반복적으로 잡음 — 버전 상태머신 가드, 세션 스코핑, **모델 설정 원자 처리(키 누출)**, **mem0 캐시 키 자격증명**([[012]]). 자가검증이면 다 놓쳤을 것.
- **Alembic을 미리 도입**한 게 모델 레지스트리 테이블 추가에서 바로 보상([[011]]).
- **단일 소스 원칙**: env 폴백을 지워 "실행=등록된 설정"을 강제([[012]]).
- 기반 먼저 → 병렬 서브에이전트(라우터·뷰) 패턴 계속 유효.

## 무엇이 잘못됐나 / 배운 것
- **절차 lapse(반복 실수)**: 매 응답 머리 `[단계 N — 이름]` 표기를 자율 실행 몰입 중 누락. 사용자가 지적 → [[013]]에 교정 규칙. **회고도 루프마다 남겨야 하는데 학습으로만 대체**한 구간이 있었음(이 문서가 그 backfill).
- **mem0 2.x API/구성 함정**: 임베딩 전용 모델·`filters=`·임베디드 qdrant([[009]]).
- **마스킹 토큰의 부작용**: `•`(비-ascii)를 HTTP 헤더로 보내 인코딩 오류 → 원격 인증은 실 토큰 보안 저장이 선행돼야([[009]] 한계).
- **Playwright 함정**: 상태 속성 셀렉터(`[aria-checked]`)는 토글 시 재해석 → 위치 기반 로케이터([[010]]).

## 다음에 다르게 / 추후
- **절차 규율 우선**: 자율이라도 단계 표기·루프별 회고를 기계적으로.
- 미완 추후: 실 MCP 연결, HIL interrupt 실제화, **실 토큰 보안 저장→외부 인증**, mem0 임베딩 레지스트리 완전 연동, sessions/approvals 부분-실패 영속 정책.

## 관련 기록
- 학습 [[008-porting-design-handoff-to-antd]] [[009-mem0-local-mlx-integration]] [[010-react-agent-single-system-message]] [[011-alembic-async-fastapi]] [[012-runtime-config-single-source]] [[013-keep-the-step-header]]
