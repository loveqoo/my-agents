# 008 — 모델 레지스트리 (LLM 설정 등록 + 에이전트 실행 연동)

상태: **실행 중 (자율)**
날짜: 2026-06-23
브랜치: `feat/agent-service` — main 머지 금지
연동: [007 실 에이전트 서비스](./007-real-agent-service.md)

> LLM(채팅)·임베딩 **모델 설정을 등록·관리**하고, 에이전트가 그중 하나를 골라
> **실행 시 그 설정으로 LLM을 띄우게** 한다. 지금은 코드가 항상 env의 MLX를 쓰는데,
> 등록된 모델을 골라 쓰도록 바꾼다.

## 1. 목표 / 비범위
### 목표
- **모델 레지스트리**: 이름·프로바이더·base_url·api_key·model id·종류(chat|embedding)·기본값·파라미터를 등록(CRUD).
- 기존 둘을 시드: 로컬 MLX **Qwen3.6-35B(chat)** + **multilingual-e5-large(embedding)**.
- 에이전트 생성 폼의 **모델 선택지 = 등록된 chat 모델**.
- **런타임**: 채팅 시 에이전트가 고른 모델을 레지스트리에서 찾아 그 base_url/api_key/model로 `ChatOpenAI` 구성(없으면 env MLX 폴백).
- UI: **모델 뷰**(사이더 신규)에서 등록/목록/삭제. api_key는 출력 시 마스킹.

### 비범위(이번)
- mem0 임베딩을 레지스트리의 embedding 모델로 연동(지금은 env 유지) — 등록·표시만, 실연동은 추후.
- 모델별 사용량/비용/헬스체크 — 추후.

## 2. 데이터 모델
```
models(id, name uniq, provider, base_url, api_key, model_id, kind[chat|embedding],
       is_default bool, params jsonb, created_at)
```
- Alembic 마이그레이션으로 추가(007에서 도입). `api_key`는 출력 시 마스킹.

## 3. API
- `/models` CRUD. `GET /models?kind=chat` 필터. (api_key는 Out에서 마스킹)

## 4. 런타임 연동
- `agent.config.model` = 등록된 모델 **이름**. chat.py가 이름으로 모델 레코드 조회 →
  `{base_url, api_key, model, params}` → `build_agent(..., model_cfg=...)`.
- `build_agent`는 `model_cfg` 있으면 그걸로, 없으면 기존 env MLX 폴백.

## 5. UI
- 사이더에 **"모델"** 추가. ModelsView: 목록 테이블 + 등록 모달(이름·종류·base_url·model id·api_key·기본값) + 삭제.
- AgentForm 모델 드롭다운 = `/models?kind=chat`.

## 6. 검증 (결과)
- [x] Alembic 마이그레이션(`add models registry`) 시작 시 자동 적용, `/models` CRUD 스모크.
- [x] 등록된 모델(`qwen3.6-35b`)로 에이전트 생성 → 그 설정으로 실행(응답/트레이스).
- [x] UI 모델 뷰(등록/목록/삭제) + AgentForm 모델 드롭다운 = 등록 chat 모델.
- [x] E2E 26종(모델 CRUD·실행·뷰 포함) + codex GATE — **P1 1건 수정**(모델 설정 원자 처리: env 키 누출 방지), P2 3건 수정(temperature 반영, 키 편집 정확 매칭/제거 가능).

## 추후
- mem0 임베딩 모델 레지스트리 연동, 모델 헬스체크/사용량, 비밀키 안전 저장(암호화/secret ref).
