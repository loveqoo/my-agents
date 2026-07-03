# 162 — mem0 테이블 미생성 시 목록 502 (초기화 직후 "relation does not exist")

## 증상
초기화(DB 리셋) 후 에이전트 상세의 메모리 목록에서:
```
메모리 목록 조회 실패: relation "mem0_memories" does not exist
LINE 1: SELECT count(*) FROM mem0_memories WHERE (payload->>$1 = $2)
```

## 근인
`mem0_memories`는 **mem0가 첫 저장(또는 Memory 인스턴스화) 시 lazy 생성**한다. 리셋/신규 DB에서 아직
아무 기억도 안 들어왔으면 테이블이 없다. 그런데 목록 조회 `Mem0Backend.list_page`는 mem0 공개 API에
offset/정렬이 없어 **`mem0_memories`를 직접 SQL**로 읽는다(스펙 127). 리셋 직후 `cur.execute(count)`가
`psycopg.errors.UndefinedTable`을 던지고 → 라우트(agents.py:839·memory_routes.py:177)가 502로 표면화.
mem0 **검색**은 `Memory` 초기화가 `CREATE TABLE IF NOT EXISTS`를 해서 되지만, **목록만** 직접 SQL이라
깨지는 불일치.

## 수정
`list_page`에서 `psycopg.errors.UndefinedTable`만 잡아 **빈 상태**(`{items:[], total:0}`)로 반환.
- 테이블 없음 = 아직 기억 0건 = **진짜 빈 상태**(실패 아님). "실패≠0건"(스펙 158) 계약은 유지 —
  연결·문법 등 다른 예외는 그대로 던져 502로 표면화한다. UndefinedTable만 정직한 empty로.
- 읽기 경로가 테이블을 **생성하지 않는다**(부수효과 0) — 첫 저장 때 mem0가 만든다.

## 검증 (비파괴)
`tests/verify_162_mem0_missing_table.py` — 별도 스키마(`public.mem0_memories` 미접촉):
1. 빈 스키마로 search_path 건 DSN → `list_page` = `{items:[], total:0}`(before=UndefinedTable).
2. 회귀: 같은 스키마에 테이블+행 생성 → `list_page` total≥1(catch가 정상 쿼리 삼키지 않음).
3. 정리: 스키마 DROP.

## 경계 (codex 162, Low·의도된 tradeoff)
- `42P01`은 "미초기화(lazy 미생성)"와 "운영 중 실수 drop / search_path 오설정으로 relation 안 보임"을
  구분하지 못한다. 후자에서도 502가 아니라 `enabled=true,total=0,items=[]`로 보인다. **mem0가 같은
  DSN으로 테이블을 lazy-create/search하는 전제**에선 테이블 부재=미초기화가 정상 해석이라 의도된
  경계다("테이블 없음=항상 장애"라는 운영 계약이 없다). 안전 불변식(다른 예외는 502로 표면화)은 유지.
  [[complement-attack-can-be-honest-boundary]] 계열 — 코드 결함 아닌 정직화로 문서에 명시.

## OUT
- 리셋 시 mem0 테이블 선생성(현재 lazy 유지 — 읽기 부수효과 회피가 더 정직). 리셋 UX(기억 0건 안내).
- 42P01의 미초기화 vs drop 구분(운영 계약 필요 시 — 현재 없음).
