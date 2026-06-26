# 034 — 세션 페이징 (P0)

상태: **승인 — 기본 제안대로 진행(1=all 폴백, 2=pageSize 20, 3=매 요청 counts). 2026-06-27.**
날짜: 2026-06-27
브랜치: `feat/agent-service` (main 머지 금지)
지배 로드맵: [033 P0](033-feature-roadmap.md) · 항목 #2

## 배경 / 문제

`GET /sessions`는 **전 세션을 한 번에** 반환하고(`sessions.py:21-27`, `order_by started_at desc`),
프론트 `SessionsView.tsx`는 `listSessions()`로 **전량 로드** 후 클라이언트에서 status 필터·배지 카운트를
계산한다. 세션이 쌓이면 페이로드·렌더가 무한정 커진다. 페이징이 없다.

**핵심 결합**: 서버 페이징을 넣으면 status 필터도 서버로 가야 한다. 안 그러면 클라이언트 필터가
"현재 페이지 안에서만" 걸려 의미가 깨진다. 배지 카운트(all/live/awaiting/error)도 전체 집계라
서버에서 계산해야 정확하다.

## 결정 (합의)

- **offset/limit + total** 방식(2026-06-27 합의). cursor 대신 — 관리자 표 UI는 페이지 번호·총계가 자연스럽다.
- 응답이 `list[SessionOut]` → **엔벌로프 `{items, total, counts}`** 로 바뀐다(브레이킹, 단일 호출처).
- **버킷→status 매핑은 백엔드 단일출처.** 프론트는 버킷 문자열(`all|live|awaiting|error`)만 보낸다.

## 범위

### 백엔드 (`packages/api/src/api/`)

1. **schema** (`schemas.py`): `SessionPage(BaseModel)` 신설
   - `items: list[SessionOut]`
   - `total: int` — **현재 필터** 적용 총 건수(페이지네이터용)
   - `counts: dict[str, int]` — 배지용 전체 집계, 키 `all|live|awaiting|error` (필터 무관)

2. **라우터** (`sessions.py` `GET ""`):
   - 쿼리 파라미터: `status: str = "all"`, `limit: int = Query(20, ge=1, le=100)`, `offset: int = Query(0, ge=0)`
   - 버킷→status 매핑(백엔드 상수):
     - `all` → 필터 없음
     - `live` → `status in (active, running, draining)`
     - `awaiting` → `status == awaiting`
     - `error` → `status == error`
   - `total` = 필터 적용 후 `func.count`.
   - `items` = 필터 + `order_by(started_at desc, id desc)`(결정적 정렬) + `offset/limit`.
   - `counts` = 전체 `GROUP BY status` 1회 → 4버킷으로 접기(`all`=합, `live`=active+running+draining, …).
   - 알 수 없는 `status` 값은 `all`로 폴백(조용한 폴백 금지 원칙 — 단 enum 밖 입력은 400 대신 all 취급이 UX상 안전. **검토 포인트 1**).

### 프론트 (`admin/src/`)

3. **api.ts** (`listSessions`):
   - `listSessions(params: { status: string; limit: number; offset: number }) → Promise<SessionPage>`
   - 타입 `SessionPage { items: Session[]; total: number; counts: Record<string, number> }` 추가.
   - 단일 호출처(`SessionsView.tsx`)만 영향 — grep로 전수 확인.

4. **SessionsView.tsx**:
   - 상태 추가: `page`(1-base), `pageSize`(기본 20), `total`, `counts`. 기존 `filter` 유지.
   - `filter`·`page` 변경 → 서버 재조회(`useEffect` 의존성). 필터 변경 시 `page=1` 리셋.
   - 배지 카운트는 서버 `counts`에서(클라 계산 제거).
   - `DataTable` 아래 antd `Pagination`(`current`/`pageSize`/`total`/`onChange`) 추가.
   - 상세 Drawer·메시지 로딩은 그대로.

## 비범위 (이번 스펙 제외)

- 세션 정렬 옵션·검색·날짜 필터(추후).
- `/sessions/users`, `/{session_id}`, `/messages`, `/end` 변경 없음.
- 오래된 세션 정리(#3, P3에서).

## 완료 조건 (검증 — 타자 우선)

1. **API 계약**: `GET /sessions?status=live&limit=20&offset=40` → `{items(≤20), total, counts}` 셰이프.
   `offset`가 total 초과 시 `items=[]`·`total` 유지. `limit` 클램프(>100 → 422 또는 100). 결정적 정렬.
   → `tests/verify_034_session_pagination.py`(httpx, 시드 위에서 수치 단언).
2. **필터 정확성**: status 버킷별 `total`이 `counts`의 해당 버킷과 일치. 페이지 가로질러도 합이 total.
3. **프론트**: 페이지 이동 시 서버 재조회·행 교체. 필터 전환 시 page=1·재조회. 배지 카운트 = 서버 counts.
   → 브라우저 선제 캡처(Playwright+시스템 Chrome): 1페이지/2페이지/필터전환 3컷.
4. **타자 검증**: codex review + 독립 서브에이전트(시그니처 변경 호출처·정렬 안정성·클램프).

## 검토 포인트 (승인 전)

1. 알 수 없는 `status` 입력 — `all` 폴백 vs 422. (기본 제안: `all` 폴백, 관대하게)
2. `pageSize` 기본값 20 적절? (조정 가능: 10/20/50)
3. `counts`를 매 요청 계산(GROUP BY 1회) vs 첫 로드만. (기본 제안: 매 요청 — 싸고 항상 정확)
