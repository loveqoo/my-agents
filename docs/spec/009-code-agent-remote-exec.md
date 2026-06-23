# 009 — 코드 에이전트 원격 실행 (프록시)

상태: **실행 중 (자율)**
날짜: 2026-06-23
브랜치: `feat/agent-service` — main 머지 금지
연동: [007](./007-real-agent-service.md)(추후 항목 "코드 에이전트 원격 호출"), [008](./008-model-registry.md)

> 코드(SDK) 에이전트는 자기 **원격 엔드포인트**에서 실행돼야 한다(코드가 LLM·구성 소유).
> `POST /agents/{id}/chat`이 코드 에이전트면 로컬 build_agent 대신 **엔드포인트로 프록시**한다.

## 1. 목표 / 비범위
### 목표
- 코드 에이전트 채팅 → endpoint로 메시지 프록시, 응답 스트리밍을 우리 SSE로 재전송.
- 세션/메시지 영속(트레이스에 `remote: true`, 그래프 `remote_call`).
- 동작·테스트용 **로컬 mock 원격 에이전트**(`/_remote/agent`) — my-agents-sdk 배포 스탠드인. 시드 Doc Translator가 이걸 가리킴.
- UI 구성 에이전트는 기존 로컬 실행 그대로.

### 비범위
- **실제 외부 배포 인증**: 등록 시 토큰을 마스킹 저장하므로 실 토큰이 없음 → 진짜 원격 인증은 추후(실 토큰 보안 저장: 암호화/secret ref). mock은 인증 미검증.
- 원격 에이전트의 상세 트레이스(메모리/MCP) 수집 — 원격이 우리 포맷을 주지 않으면 최소 트레이스만.

## 2. 원격 계약 (mock이 구현)
- `POST <endpoint>` body `{messages:[{role,content}]}`, 헤더 `Authorization: Bearer <token>`.
- 응답 **SSE**: `data: {"text": "..."}` 프레임들 + `data: [DONE]`. (우리 chat과 동일 포맷)

## 3. 구현
- `mock_remote.py`: `POST /_remote/agent` — 메시지 받아 간단한 응답을 SSE로 스트리밍(개발용 더블).
- `chat.py`: `agent.source == 'code'`면 httpx로 endpoint에 스트리밍 POST → text 프레임 재전송 → 트레이스(remote)·세션 영속. 아니면 기존 로컬 경로.
- `seed.py`: Doc Translator endpoint를 로컬 mock(`/_remote/agent`)로.
- 의존성: `httpx`.

## 4. 검증 (결과)
- [x] 코드 에이전트 채팅 → 원격(mock) 응답 스트리밍(8프레임) + 세션/메시지/트레이스(`remote:true`) 영속.
- [x] UI 구성 에이전트 로컬 실행 회귀 없음. 전체 E2E 27 passed(코드 에이전트 원격 포함).
- [x] codex GATE — P2 2건 수정(SSE `data:` 관대 파싱, 원격 에러 본문 포함). 토큰 마스킹 시 인증 헤더 생략(• 비-ascii 헤더 오류 방지).

## 추후 / 알려진 한계
- **dev-mock 호스트 의존(codex P1)**: 시드 코드 에이전트가 `http://127.0.0.1:8000/_remote/agent`(자기 자신)를 가리킴 → API 포트/토폴로지가 다르면 깨질 수 있음. `REMOTE_AGENT_BASE` env로 오버라이드. 실제 코드 에이전트는 **자기 외부 URL**을 쓰므로 이 self-call은 데모 한정.
- 실 토큰 보안 저장 → 진짜 외부 배포 인증(현재 마스킹 토큰이라 인증 헤더 생략). 원격 트레이스 표준(A2A) 수집. 부분-실패 턴 미영속(로컬 경로와 동일 정책).
