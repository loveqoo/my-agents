# 390 — verify 격리 하네스 Phase 2: 전용 서버 러너 + VERIFY_BASE 주입

> 상태: 초안(AI 작성 → 인간 검토). 스펙 385 P2 아웃의 집행 — 백로그 "verify 스위트 격리" 완결편.
> 참고: 385(P1 asgi 층)·307(_throwaway_db)·384(http 17건 triage)·회고 387(virgin이 오염/노후 심판)

## 목표

http 층 66개(라이브 :8000 전제)를 **스크립트마다 virgin DB + 전용 uvicorn(임시 포트)** 로 격리 —
라이브 dev 서버·DB 완전 무접촉. 격리(KNOWN_DRIFT)의 "오염" 사유들을 재판정(virgin 서버가 심판).

## 설계 — 발명 없는 배선(392 결)

1. **러너 `tests/_throwaway_server.py`**: _throwaway_db의 _create/_drop 재사용. 빈 포트 확보 →
   uvicorn 기동(부팅 lifespan=alembic+seed — 별도 부트스트랩 불요) → health 대기 → 대상 실행 →
   종료+drop. **자기참조 시드 정렬**이 핵심: `SELF_BASE_URL`(served MCP)·`MOCK_LLM_BASE_URL`·
   `REMOTE_AGENT_BASE`를 임시 포트로 주입(seed가 이미 env 오버라이드 지원 — served_url만 이번에
   env 지원 추가, 기본값 불변).
2. **VERIFY_BASE 치환(45파일)**: 하드코딩 `http://127.0.0.1:8000` →
   `os.environ.get("VERIFY_BASE", ...)`. 라인 단위 3분류 — ①클라이언트 BASE ②앱에 등록하는
   자기참조 URL(둘 다 치환 — 같은 서버) ③**guard_url/net_guard 판정 데이터(치환 금지)**.
   **fast-worker 위임**(측정 마감: ast 전수 + 잔존 grep 사유표) — 위임 갭 교정 1호.
3. **run_suite 통합**: http 층 실행을 isolate_server로 래핑(타임아웃 300s — 서버 부팅 포함).
   비용: 66 × (부팅 ~15s + 테스트) — http 층은 test-all 전용이라 수용.

## 실증(러너 검증)

- verify_072를 러너로 실행: 임시 포트 서버 기동·시드·자기참조(mock LLM/임베딩) 정렬·컬렉션
  생성·인제스트·검색까지 관통 확인. 잔여 실패 2건은 **노후로 판정**(virgin 심판): 이름 규칙(148)
  이전 `_` 접두(400→dash로 수선), ready 상태 단언(검색은 3건 동작 — 상태 모델 드리프트).

## 진행 기록(2026-07-18)

- **fast-worker 위임 결과(치환)**: 38파일 수정·55줄 치환·ast 실패 0·잔존 11줄 전부 사유표
  (guard 계열 판정 데이터·순수 픽스처·REMOTE_AGENT_BASE 기주입 2건). 애매 판단 3건은 집행 전
  보고 방식(추측 금지 규율 준수) — 검토 후 전부 승인: ①guard 제외를 "얇은 래퍼 경유 입력"까지
  확장 ②API_BASE→VERIFY_BASE rename(소비자 부재 확인) ③061 단위 픽스처 일관 치환.
- **스팟 판정**: verify_101 H6(delete→interrupt 미발동)이 **virgin 서버에서도 동일 실패** —
  "라이브 환경/데이터 차이"가 아니라 재현되는 실제 드리프트로 상향(233 인프로세스는 통과하므로
  라이브-HTTP 경로 특이 — 별도 조사감). verify_072는 러너 하 관통(이름 규칙 400 수선 후 ready
  상태 단언만 노후 잔존).
- 씨앗 그물 SUITE_OK(치환 무회귀).

## 완료 조건(측정)

- C1: 치환 45파일 — ast 전수 OK, 잔존 8000 리터럴은 판정 데이터/주석뿐(사유표).
- C2: `run_suite http`가 전 스크립트를 virgin 서버로 실행(라이브 무접촉 — dev DB 행 수 전후 동일).
- C3: KNOWN_DRIFT 재판정 — "오염" 사유 격리들을 virgin 서버 결과로 해제/노후 확정(수치 보고).
- C4: 씨앗 그물 SUITE_OK·asgi 층 불변·suite 51/51 무회귀.
