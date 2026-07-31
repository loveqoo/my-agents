# 스펙 436 — 이벤트 버스 합류: 재인덱싱·평가 런(335 씨앗 잔여 소형)

## 발단

스펙 335가 만든 배경 잡 이벤트 채널(pub/sub + SSE → admin 우하단 알림)은 **인제스트만** 발행한다.
재인덱싱(수 분 걸릴 수 있음)과 평가 런(배경 실행)은 끝나도 조용하다 — 백로그 씨앗 "각 publish 한 줄".

## 결정

### BE — 발행 3+2곳(기존 인제스트 페이로드 형태 미러)

- **재인덱싱**(`rag/reindex.py`): 성공 `{type:'reindex', status:'ready', collection, collection_id,
  chunks}` · 실패 `{…status:'error', error}` · **취소**(434 해제 헬퍼) `{…status:'error',
  error:'취소됨…'}` — 이력과 같은 사실을 알림으로도.
- **평가 런**(`eval_execution.py`): `_persist_report` 뒤 `{type:'eval', status:'ok', dataset, run_id,
  score, passed, total}` · `_mark_run_error` 뒤 `{…status:'error', error}`. dataset 이름은 그 세션에서
  조회해 박제(스칼라 — 세션 밖 ORM 금지, 스펙 434 교훈).
- 발행은 전부 best-effort(publish는 이미 드롭 허용 설계 — 알림이지 진실이 아님, 335 계약 유지).

### FE — 타입 유니언 + 알림 분기

- `api.ts`: `IngestEvent` → `BusEvent` 유니언(`ingest | reindex | eval`) — 기존 이름은 하위호환 별칭.
- `AdminShell`: `type==='reindex'` → "재인덱싱 완료 — {collection} · 청크 N" / 오류·취소는 error 알림.
  `type==='eval'` → "평가 완료 — {dataset} · {passed}/{total} (점수 score)" / error 알림.

## 완료 조건(측정) — 결과

`tests/verify_436_event_bus.py` 5/5(publish 캡처):
1. ✅ 재인덱싱 성공(chunks=54)·실패(실행 내부 주입)·취소(434 경로) 발행 — 페이로드 필드 단언.
2. ✅ 평가 ok(dataset·passed/total)·error 발행.
3. ✅ tsc 0 + 브라우저(`verify-436-reindex-notify.mjs` 3/3): 실제 재인덱싱 → 우하단 "재인덱싱 완료" 알림.
4. ✅ verify_312·434 green · 그물 코드 회귀 0.

**검증이 잡은 선재 실결함(보너스 수리)**: 재인덱싱 **실행 내부 실패** 시 `rollback()`이 ORM 객체
(from_model·c)를 만료시키는데 이력 기록이 만료 속성에 접근해 **MissingGreenlet**으로 터졌다 —
이력 누락 + 500 대신 내부 오류 누출(스펙 312 이래 잠복, 실패 경로 테스트가 없어 무증상).
스펙 434의 `_cancel_snap` 스칼라를 오류 경로에도 재사용해 수리("정리·오류 경로에 ORM 금지"의 재확인).
FE 타입은 기존 `ReindexEvent`(이력)와 이름 충돌해 `ReindexBusEvent`로 구분.

## OUT(경계)

- 영속 알림함(놓친 이벤트 재생 — 씨앗 마지막 항목, 별개 설계 규모).
- 알림 묶음·읽음 처리 등 UI 고도화.
