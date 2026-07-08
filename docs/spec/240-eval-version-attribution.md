# 스펙 240 — 평가의 버전 귀속 + 경량 환경 기록 (AgentOps 루프 A)

## 배경 (AgentOps 로드맵 A — 2026-07-08 채택)

"v17=91, v18=94"를 말하려면 평가 실행이 **어느 버전**에 대한 것이었는지 남아야 한다. 지금 EvalRun은
에이전트·모델명만 기록 — 버전 무귀속. 또한 "왜 예전엔 94였는데 지금 87인가"의 진단 단서(실행 환경)가
없다. 외부 제안의 "완전 재현 Snapshot"은 과설계(RAG 인덱스 스냅샷=데이터 복제 비용)로 판단, **경량
환경 기록**으로 시작한다(재현 보장이 아니라 귀속·진단이 목적 — 정직한 계약).

## 변경

### DB (마이그레이션 f240a1b2c3d4, head f212a1b2c3d4 뒤)
- `eval_runs.agent_version`(String(20), NULL) — 실행 시점 에이전트 **활성 버전** 박제(과거 행 NULL=미기록).
- `eval_runs.env`(JSONB, NULL) — 경량 환경 기록:
  `{model: {name, params}, impl, ephemeral, mcps: {server: [enabled_tools]}, collections: {name: {docs,
  chunks, embedding}}, embedding?}` — 에이전트 런은 배선 표면 기준, RAG 런은 대상 컬렉션 기준.

### 백엔드
- `_env_snapshot(session, agent|rag_collection)` 헬퍼 — 위 구조 수집(레지스트리 params·컬렉션
  doc/chunk 카운트·임베딩 모델명·MCP enabled_tools). 실패는 부분 기록(진단 부가층 — 실행을 막지 않음).
- EvalRun 생성 3지점(단일 모델·그룹·일반)에 `agent_version=agent.active_version` + env 박제.
- RunOut에 `agentVersion`·`env` 노출.

### UI (EvalView)
- 실행 이력·문제집 최근 런·성적표 헤더에 버전 칩(`v3`) 표시(무버전 과거 런은 표기 생략).
- 비교 드로어(138)에 두 런의 버전 표기 — "v3 vs v4" 회귀 비교가 읽히게.
- env는 성적표에서 접이식 "실행 환경"으로(값 나열 — 진단용).

## 검증
- 마이그레이션 헤더 그래프 검증(단일 head·중복 0·고아 0 — [[hand-authored-migration-ids-collide-silently]]).
- 실측: 평가 실행 → EvalRun.agent_version=활성 버전·env에 모델/컬렉션 기록. 버전 활성화 후 재실행 →
  다른 버전 박제(귀속이 활성 버전을 따라감을 증명).
- UI 버전 칩 브라우저 확인. verify eval 무회귀(137 계열). codex 적대.

## 완료 조건
- 모든 새 평가 런이 버전+환경을 남기고, UI에서 "어느 버전의 성적인지" 보인다. 과거 런은 NULL로 정직
  표기. B(자동 회귀)가 이 축을 그대로 사용할 수 있다.

## 검증 결과 (2026-07-08)
- 마이그레이션 f240a1b2c3d4 적용(DB head 일치·단일 head·중복 0). verify_240 5/5: 실행 완료·버전
  박제=활성 버전 일치(**발견: 새 에이전트=초안만이라 활성 None → 런도 None = 정직 기록**)·env 모델/
  도구 기록·**버전 전환 추적(None→v1 활성화 후 재실행=v1 박제)**·목록 노출. 브라우저 3/3(이력 칩·
  성적표 헤더·실행 환경 접이식).
- codex 4건 판정:
  - **#3 ModelConfig.params 비밀 노출(P1)** → **수정**: `_env_redact` 재귀 마스킹(api_key/token/secret/
    authorization/password 키) 후 기록.
  - **#2a 오버라이드 런 name/params 불일치**(name=B·params=A 거짓 기록) → **수정**: `_model_env`로
    그 모델의 params를 조회·기록(단일·그룹 양쪽).
  - **#2b Collection.embedding_model_name ORM 부재**(RAG 배선 에이전트 → AttributeError→partial)
    → **수정**: ModelConfig 조인. RAG 배선 실측(docs-kb: docs·chunks·embedding 기록, partial 없음).
  - **#1 박제 시점 드리프트** → **문서화 경계**: agent_version은 **시작 시점** 활성 버전. 백그라운드
    실행 중 버전을 활성화하면 결과는 새 서빙 config로 나올 수 있다(런은 짧고, B단계 자동 회귀는
    activate가 트리거라 순서 보장 — 실무 위험 낮음. 필요 시 종료 시점 재검증 후속).
