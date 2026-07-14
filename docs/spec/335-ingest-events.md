# 335 — 배경 잡 완료 이벤트(SSE) + 전역 알림

## 배경 / 요구 (사용자, 2026-07-14)

"백그라운드로 돌아도 성공/실패는 이벤트로 알려줄 수 있어야" — 스펙 334의 배경 인제스트는 문서
드로어 폴링으로만 관찰돼, 드로어를 닫으면(다른 메뉴에 있으면) 완료·실패를 알 길이 없다.

## 설계

### 이벤트 채널 — GET /events (SSE, 인증)
- `api/events.py`: 프로세스 내 pub/sub — `publish(event)`가 구독자 큐 전부에 비블로킹 전달
  (큐 상한 초과 = 느린 구독자 이벤트 드롭, no-block). 15초 heartbeat(`: ping`)로 연결 유지,
  구독 해제는 finally(연결 끊김 자동 정리). 채팅 SSE와 같은 StreamingResponse 결.
- **의미론(정직)**: 이벤트는 *알림*이지 진실이 아니다 — 구독 전/브라우저 꺼짐 동안 발생분은
  유실되고, 상태의 진실은 여전히 문서 status(+드로어 폴링). 영속 알림함은 OUT.
- **경계(정직)**: in-process 버스 — 멀티 파드에선 자기 파드가 처리한 잡만 알린다(k8s 백로그
  합류 시 Redis pub/sub 등으로 승격, 지금은 단일 프로세스 dev 도구).

### 발행 지점 — 배경 인제스트(스펙 334)
- `_execute_ingest` 완료 시: `{type:"ingest", status:"ready", filename, collection, chunks, document_id, collection_id}`
  실패 시: `{..., status:"error", error}`(이미 마스킹된 Document.error 문구 재사용 — 비밀 미노출).
- 버스는 범용 — 이후 재인덱싱·평가 런 등 다른 배경 잡도 같은 채널로(OUT 씨앗).

### 프론트 — 전역 구독 + antd notification
- api.ts `openEventStream(onEvent)`: EventSource(쿠키 동행, 자동 재연결) 래퍼(BASE 단일 출처).
- AdminShell 마운트 시 구독: ingest 이벤트 → `notification.success/error`
  ("movies.jsonl 임베딩 완료 — 청크 70개" / 실패 사유). **어느 메뉴에 있어도** 뜬다.
  문서 드로어 폴링은 유지(진실 동기화 — 이벤트는 UX 겹).

## 검증 (완료 조건)

1. verify_335: E1 버스 pub/sub 왕복(구독 후 발행 → 수신) · E2 느린 구독자 드롭(no-block, 발행이
   안 막힘) · E3 **인제스트 통합**: 구독 → 업로드 → ready 이벤트 수신(chunks 실측 일치) ·
   E4 실패 인제스트 → error 이벤트+사유 · E5 SSE 엔드포인트 스트림 실측(heartbeat·data 프레임).
2. 브라우저 e2e: **문서 드로어를 열지 않은 채**(다른 메뉴) 업로드 → 전역 알림 토스트 등장.
3. lint/mypy/tsc/build · 334 무회귀 · codex 적대 P1/P2 0.

## OUT

- 영속 알림함(놓친 이벤트 재생) · 멀티 파드 버스(Redis — k8s 합류) · 재인덱싱/평가 런 이벤트
  (버스는 준비됨 — 후속 한 줄) · 알림 설정(끄기/필터).
- VITE_API_TOKEN 단독 모드 SSE 인증(EventSource가 헤더 미지원 — 알림만 미동작, 주석 명시) ·
  운영용 graceful shutdown 계약(run()은 dev 전용 — 배포는 uvicorn 직접 기동 시 자체 설정).

## 결과 (2026-07-14 실행)

- 설계대로 + 실행 중 **운영 발견 1건**: 열린 SSE 연결이 uvicorn 기본 graceful shutdown을 영원히
  잡아 **reload가 "죽은 척" 멈춤**(dev 서버가 실제로 그 상태에 빠져 있었음 — 프로브가 발굴).
  `timeout_graceful_shutdown=5`(run()+nohup 레시피, 메모리 갱신). e2e도 같은 이유로 networkidle
  대기가 불성립 → 요소 기준 대기로.
- codex 적대 P1 0·P2 3·P3 2 반영: ①동시 구독 상한(_MAX_SUBS=20, 초과 429 — 알림은 UX 겹이라
  거절해도 기능 무손실) ②알림 폭주 → notification key(컬렉션+상태) 병합 ③token 단독 모드
  EventSource 인증 불가는 정직 경계 주석(쿠키 UI 무영향) ④검증 보강(E6 429·E7 구독 해제 누수 0)
  ⑤graceful 계약은 dev 전용 명시.
- 검증: VERIFY335_OK 7/7(버스 왕복·no-block·성공/실패 이벤트·프레임·상한·누수 0) ·
  VERIFY335_UI_OK(**드로어 없이** 전역 성공/실패 알림 실측) · 334 무회귀 · lint/mypy/tsc/build 클린.
