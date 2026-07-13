# 330 — init_db create_all 폴백 제거: 마이그레이션 fail-fast

## 배경 / 동기

스펙 329 codex P1이 실증한 함정: alembic upgrade가 실패해도 init_db가 warning만 남기고
create_all 폴백+head 스탬프로 **조용히 우회** → 고장난 마이그레이션이 성공처럼 보이고 스키마
드리프트가 버전 기록과 어긋난 채 침묵(db.py:98-128). 폴백은 스펙 059 시절 "첫 설치 복원력"의
정식 경로 B였으나, 지금은 마이그레이션 체인이 virgin DB를 처음부터 깨끗이 빌드하므로(329 실측)
**폴백이 발동하는 유일한 경우 = 진짜 고장**이고 그때 폴백은 고장을 가리는 역할만 한다.

사용자 결정(2026-07-14): **완전 제거(fail-fast)** — alembic을 스키마 단일 진실로.

## 변경

### C1. db.py init_db — 폴백 소거
- `try/except → create_all+stamp` 블록 제거. upgrade 실패 시 **조치 메시지 로그 + RuntimeError**
  (부팅 중단): 원인 후보(①새 마이그레이션 파일 결함 ②DB alembic_version이 코드가 모르는 리비전 —
  구 코드로 신 DB 부팅 ③스키마 수동 드리프트)와 진단 명령(`alembic current`/`history`) 안내.
- `_preflight`(연결 실패 명확화)·시드·stale reindex 회수는 그대로.
- pgvector 확장은 경로 A의 마이그레이션 `b2c3d4e5f6a7`(CREATE EXTENSION IF NOT EXISTS)이 이미
  보장 — 폴백의 확장 보장 로직도 함께 소멸.

### C2. 경로 B 잔재 정리 (부수)
- `seed.py _seed_mock_provider_models` docstring의 "create_all 폴백에서만 도달" 정정 — 이 블록은
  이제 "providers가 비워진 DB의 재부팅 자가복구"로만 도달(살아있는 경로라 블록 자체는 보존).
- 마이그레이션 파일 내 경로 B 언급 주석(`c9d0e1f2a3b4`·`d0e1f2a3b4c5`)은 **불변 이력이라 미수정**.
- `verify_059_integration.py`: 경로 B(폴백) 분기 제거 — A(alembic) 단일 경로 검증으로 재작성.
  "두 경로 수렴" 계약(learning 062)은 경로가 하나가 되면서 자연 소멸.

### C3. 새 계약 검증 — tests/verify_330_failfast.py
서브프로세스+스크래치 DB(자체 생성·drop, _throwaway_db 패턴)로:
- **F1 fail-fast**: alembic_version='deadbeef'(코드가 모르는 리비전)인 DB → init_db **예외로 중단**,
  create_all 부수효과 0(테이블 미생성)·버전 미변경(스탬프 안 함) — 조용한 우회의 여집합 전부 단언.
- **F2 virgin 정상**: 빈 DB → init_db 성공 → alembic_version==실제 head·rag_chunks 존재(확장+체인).
- **F3 멱등**: 정상 DB 재부팅(2회째 init_db) 무예외.

## 완료 조건

1. verify_330 F1~F3 통과(스크래치 DB 실측 — 폴백 경고 문자열이 어디에도 안 뜸).
2. `create_all`이 제품 코드(packages/api/src)에서 사라짐(grep 0 — 모델 metadata 선언은 무관).
3. verify_059(A 단일)·verify_329(전 체인) 무회귀 · `make lint format-check typecheck` 클린.
4. 라이브 dev 서버 정상 재기동(head 정합 상태라 무영향).
5. codex 적대 리뷰(제거된 폴백이 지탱하던 사례의 여집합 — learning 060 "폐기 경로의 행동 집합 열거") P1/P2 0.

## OUT

- k8s 마이그레이션 Job 분리(백로그 P1 ② — 이 스펙은 그 선행 정지작업).
- 다운그레이드/브랜치 전환 UX(구 코드+신 DB는 이제 명확히 죽음 — 메시지로 안내만).

## 결과 (2026-07-14 실행)

- C1~C3 완료 + 실행 중 발견 여집합: **verify_058이 폴백 내부 순서를 소스 문자열로 단언**하고
  있었음(제거 즉시 크래시) → G1 블록을 새 계약(fail-fast·create_all/stamp 부재·조치 메시지)으로
  재작성. smoke_303·_throwaway_db·models.py 주석의 폴백 언급도 정정.
- codex 적대(learning 060 폐기 행동 열거): P1 0·P2 3 전부 반영 — ①fail-fast 메시지에 pgvector
  권한 원인 추가(관리형 PG 비수퍼유저가 잘못된 축을 디버깅하지 않게) ②F4 신설: 확장 **선설치
  없는** DB 부팅 성공으로 "CREATE EXTENSION 보장이 마이그레이션에 승계"를 실증(F2의 _create는
  확장을 선설치해 이 보장을 검증 못 했음) ③README 부팅 계약 3곳 정정. 폐기 행동 5종(확장 보장/
  스키마 생성/스탬프/seed 도달/이중 throw) 전수 판정 — 승계 3·의식적 폐기 2.
- 검증: VERIFY330_OK 12/12(스크래치 DB 3개 — broken/virgin/no-ext) · verify_058/059/329 무회귀 ·
  lint/mypy 클린 · 라이브 dev 서버 무영향 재기동.
