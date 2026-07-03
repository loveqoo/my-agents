# 140 — mem0 테이블 미생성 시 목록 502 (스펙 162)

실사용 버그(다른 디바이스 초기화 후 에이전트 상세): `메모리 목록 조회 실패: relation "mem0_memories"
does not exist`.

## 근인
`mem0_memories`는 mem0가 **첫 저장 시 lazy 생성**. 리셋 직후 테이블 없음. 목록 조회 `list_page`는
mem0 공개 API에 offset/정렬이 없어 **직접 SQL**(스펙 127)로 읽어서 `UndefinedTable`을 던지고 → 라우트가
502. mem0 **검색**은 `Memory` 초기화가 `CREATE TABLE IF NOT EXISTS`를 해 되지만, **목록만** 직접 SQL이라
깨지는 불일치.

## 배운 것
- **"실패≠0건"(스펙 158)의 반대 함정도 있다: 진짜 빈 상태를 실패로 위장**. 158은 저유사도를 0건으로
  숨기는 걸 고쳤고, 162는 그 반대 — 미초기화 테이블(=진짜 0건)을 502 실패로 보이게 했다. 두 계약은
  대칭: **실패는 실패로, 빈 상태는 빈 상태로**. 판별 축은 예외 종류 — UndefinedTable=미초기화=empty,
  나머지(연결·문법·권한)=실패=502. catch를 좁게(특정 예외만) 잡아야 158을 안 되돌린다.
- **우회 경로가 초기화 부수효과를 우회하면 불일치가 생긴다**. mem0를 우회한 직접 SQL(127, 페이지네이션
  때문)이 mem0의 lazy CREATE도 우회 → 검색은 되고 목록만 깨짐. 우회는 성능/기능 이득의 대가로 **원본이
  보장하던 불변식(테이블 존재)을 잃는다** — 그 틈을 명시적으로 메워야(여기선 UndefinedTable→empty).
- **읽기 경로는 부수효과 0 유지**. 목록 조회가 테이블을 CREATE하지 않는다 — 첫 저장 때 mem0가 만든다.
  읽기가 스키마를 바꾸면 관측이 상태를 바꾸는 셈. lazy 생성은 쓰기 쪽 책임으로 둔다.
- **미문서 경계 정직화(codex Low)**: 42P01은 미초기화 vs 운영 중 drop을 구분 못 함 → 후자도 empty.
  mem0가 같은 DSN으로 관리하는 전제에선 의도된 tradeoff. 고치지도 기각도 아닌 **문서 명시**
  ([[complement-attack-can-be-honest-boundary]]) — 여집합 공격(테이블 drop)이 성공해도 코드결함 아님.
- **실기기로 재현 못 하는 상태는 단위로 충실히 재현**. 이 디바이스는 테이블이 있어(기억 존재) 미생성
  경로를 못 만든다 → 별도 스키마(search_path)로 UndefinedTable을 격리 재현(비파괴, public 미접촉).
  list_page가 self._dsn만 쓰는 걸 확인해 전체 백엔드 인스턴스화(=테이블 생성) 없이 스텁 호출.

## 검증
verify_162 3/3(H1 테이블 없음→빈 상태·H2 회귀 테이블+행→정상 조회·본문 반환). 별도 스키마 비파괴.
codex 결함 0(158 계약 안 되돌림 확인)·Low 미문서 경계 1(문서 명시). import 심볼은 verify H1이 실행 확인.

## OUT
- 리셋 시 선생성(lazy 유지가 더 정직). 42P01 미초기화 vs drop 구분(운영 계약 필요 시). 리셋 UX 안내.

[mem0-lazy-table,failure-vs-empty-symmetric,bypass-loses-invariant,read-path-no-side-effect,honest-boundary-doc,nondestructive-schema-repro]
