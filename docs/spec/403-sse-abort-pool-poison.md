# 403 — SSE 이탈 커넥션 풀 오염 봉합(스펙 402 실구멍 보고의 수선)

> 상태: **완료** · 2026-07-19 (P1~P4 + codex 소견 2건 완성형 반영)
> 발단: 402의 068 조사에서 실측 — 클라이언트가 chat SSE를 중도 이탈(탭 닫기·모바일)하면 ASGI
> 태스크 취소가 in-flight 커넥션을 오염시켜 **후속 요청의 인증 쿼리가 비결정 500**. codex가
> 실사용 재현 조건으로 확인(실구멍). 지금까지는 테스트 하네스(드레인)로 피했을 뿐 앱은 미봉합.

## 처방(3지점 + 회귀 테스트 — codex 402 스케치 그대로)

- **P1 메인 엔진 자가치유**: `db.py` `create_async_engine(..., pool_pre_ping=True)` —
  오염(닫힌) 커넥션을 checkout 시 재검증·폐기해 후속 요청이 자가 복구. (오버헤드=checkout당
  SELECT 1 한 번 — 개인/팀 규모에서 무시 가능.)
- **P2 체크포인터 풀 검증**: `checkpointer.py` `AsyncConnectionPool(..., check=
  AsyncConnectionPool.check_connection)` — psycopg 풀도 checkout 시 죽은 커넥션 검출·교체.
- **P3 정리 취소-보호**: `chat.py` `event_stream` finally의 `release_thread`를
  `asyncio.shield`로 감싸 클라 이탈 취소가 정리 도중을 끊지 못하게(끊기면 체크포인터
  커넥션이 "another command in progress"로 오염 — 402 실측). 외곽 CancelledError는 suppress,
  내부 정리는 완주.
- **P4 회귀 테스트 `verify_403_sse_abort.py`**: 실 uvicorn(throwaway)에서 ①SSE 첫 프레임 후
  의도적 abort ×N ②직후 인증 요청(GET /sessions 등) ×M 전부 200(500 무발생) ③정상 채팅 1회
  왕복 그린. 반복(비결정 대비 ≥3회) — 402의 068이 재현기였던 그 패턴을 이번엔 **공격 축**으로.
  +설정 자체 단언(pool_pre_ping·check 배선 — installed≠covering 교훈: 장치가 꺼지면 테스트가 잡게).

## 완료 기준(수치) — 달성(실측)

- [x] **공격 실증**: 봉합 전 코드(stash)에서 abort 폭격에 chat 시작이 **200/500 교차**(오염 커넥션
      격발) — 봉합 후 3라운드 전부 200·인증 15발 500 무발생·**체크포인트 잔류 0**. verify_403 18/18.
- [x] verify_068(드레인 하네스) 무회귀 그린 — 방어/공격 쌍.
- [x] make test SUITE_OK(89) + metrics-fast 전판. suite 51/51은 마감 관문(실행 로그 별도).
- [x] codex 스팟 → **P1 2건 완성형 반영**: ①참조 없는 shield는 "완주"가 아니라 "방치"(고아 태스크)
      → 관문 헬퍼 `shielded_release`(강참조 세트+완료 콜백) 신설, chat이 경유. ②**A2A 로컬 서빙에
      폐기 관문 부재**(388 P2가 체크포인터를 붙인 뒤 346 관문 미승계 — 완료 턴 체크포인트 TTL까지
      잔류+같은 오염 후보) → chunks() finally에 같은 관문 적용(paused=interrupt 보존).
      P2(정리 불변식 미단언) → A5(abort 후 체크포인트 잔류 0)로 반영.

## OUT

- 배경 태스크 전반의 취소-보호 일반화(spawn 계층) — 별도.
- pool_size/max_overflow 튜닝(k8s 항목과 합류).
