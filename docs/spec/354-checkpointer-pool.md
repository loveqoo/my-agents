# 354 — 체크포인터 커넥션 풀 (단일 커넥션 공유 → pipeline 충돌 봉합)

## 왜 (실측·인과 확증)

데이터 초기화 후 채팅이 에러를 뱉었다: `another command is already in progress / cannot enter
pipeline mode, connection not idle`. 채팅은 느린 게 아니라 **실패**하고 있었다.

**근인**: `checkpointer.py`가 `AsyncPostgresSaver.from_conn_string(dsn)`으로 **단일 AsyncConnection**을
열어 싱글턴 공유한다(langgraph 소스 확인: `AsyncConnection.connect(..., autocommit=True,
prepare_threshold=0, row_factory=dict_row)`). langgraph의 일부 메서드(aput·adelete_thread 등)는
내부적으로 **pipeline**을 쓰는데, 단일 커넥션을 **여러 코루틴이 동시에** 쓰면 한쪽이 pipeline을 연
사이 다른 쪽이 같은 커넥션을 건드려 충돌한다.

**방아쇠는 스펙 348**: 배치 스케줄러를 켜자 checkpoint-cleanup 스윕이 죽은 스레드를 대량
`adelete_thread`로 지우며 커넥션을 점유했고, 그 사이 온 채팅이 충돌했다. **인과 확증**: 콜드 부팅 직후
(스윕 전) 채팅은 정상, pipeline 에러 0회. 배치가 안 돌던 348 이전엔 안 드러났다.

## 설계 — 단일 커넥션 → AsyncConnectionPool

langgraph `AsyncPostgresSaver(conn)`의 `conn`은 커넥션 **또는 풀**을 받는다(3.1.0). 풀을 주면 각 작업이
풀에서 자기 커넥션을 빌려 동시성 안전(채팅·배치 스윕이 서로 다른 커넥션).

- 풀 kwargs는 from_conn_string과 **동일**하게: `autocommit=True, prepare_threshold=0,
  row_factory=dict_row`(langgraph가 이 설정을 전제 — 빠뜨리면 조용히 깨진다).
- `open=False` + `await pool.open()`(psycopg_pool 권장 — 생성자 open은 경고).
- `max_size`는 동시 채팅+배치 수용(예 20). 종료 시 `pool.close()`.
- graceful 유지: 풀 오픈/setup 실패는 기존처럼 None 폴백(HIL 게이트 비활성).

## 완료 조건 (수치)

- **C1** 체크포인터가 풀 기반 — `_pool`이 AsyncConnectionPool, saver가 그 풀로 생성.
- **C2** **배치 스윕과 채팅 동시 실행 시 pipeline 에러 0회**(회귀 재현 봉합) — 스윕을 트리거한 상태로
  채팅 N턴, `another command in progress`/`pipeline mode` 0.
- **C3** HIL 흐름 무회귀 — 승인 게이트 인터럽트→재개가 여전히 durable(verify_041/346).
- **C4** 전체 기능점검(구남님 지시): `make test` 씨앗 그물 초록 + 실제 채팅 정상 + 배치 스윕 정상.

## 결과 (2026-07-15)

- `checkpointer.py`: 단일 커넥션 → `AsyncConnectionPool`(min 1·max 5) + `AsyncPostgresSaver(pool)`.
  풀 kwargs는 langgraph와 동일(autocommit·prepare_threshold=0·row_factory=dict_row).
- **C2 봉합 확증**: checkpoint-cleanup 스윕을 동시 트리거하며 채팅 5턴 → **pipeline 에러 0/5**(로그도 0).
  수정 전 오래 뜬 서버에선 스윕과 채팅이 충돌해 채팅이 에러였다.
- **C3/C4 전체 기능점검**(구남님 지시): 씨앗 그물 SUITE_OK · verify_041(HIL 승인) ✅ · verify_346 16건 ✅ ·
  lint/typecheck 클린.

### codex 적대 검증 반영

- **P1 재진입 경합(고침)**: `sweep()`이 배치 프로세스에서 fallback으로 `init_checkpointer()`를 부르므로
  동시 진입 가능 → 풀 두 개 생성·전역 뒤집힘. `asyncio.Lock` + 성공 후에만 전역 publish로 봉합.
- **P2 풀 크기(고침)**: langgraph saver는 내부 `self.lock`으로 DB 작업을 **직렬화**하므로 큰 풀은
  처리량을 안 늘리고 idle 커넥션만 예약(too-many-connections 위험). max 20→5·min 4→1로 낮춤.
  얻는 건 처리량이 아니라 **pipeline 충돌 회피**임을 주석에 정정.
- **P1 멀티워커 setup 경합(백로그)**: fresh DB에 워커 여러 개가 동시 `setup()`하면 checkpoint_migrations
  PK 충돌로 일부 워커 HIL 비활성 가능. 현재 단일 워커라 낮은 위험 → 백로그(배치의 advisory lock 패턴 재사용).

## OUT

- 앱 본체(SQLAlchemy)의 커넥션 풀은 별개(이 스펙은 langgraph checkpointer 전용).
