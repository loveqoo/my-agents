# 098 — 세션 목록 서버측 검색 (제안 #8)

> 상태: 초안(AI 작성, 인간 검토). 제안 8항목 중 #8. 사용자 스코프 선택: **"메타데이터 검색"**
> (세션 ID + user_id + 에이전트 이름). 메시지 본문 전문검색은 **비목표**.
> 참고 자산: spec 034(세션 페이징 offset/limit+total+status 필터 — 확장 토대)·spec 067(세션 RBAC
> `_own_scope`·배지 스코프)·spec 055(agent_id 필터 — 같은 방식의 파라미터 추가)·spec 072/084/097
> (retrieval "로컬 필터 vs 서버 검색" 구분)·docs/spec/CLAUDE.md RBAC 체크리스트(**트리거됨**).

## 1. 배경 / 문제 (코드 실증)

세션 목록은 스펙 034로 **서버 페이징**(offset/limit + total + status 버킷 필터 + 배지 카운트)이 완비돼
있으나 **검색이 없다**. `admin/src/api.ts:listSessions`는 `status·agent_id·limit·offset`만 받고,
`SessionsView.tsx`는 status Radio + Pagination만 노출한다.

**왜 서버측이어야 하나 (로컬 필터 부정직):** 세션은 서버 페이징이라, 메모리/컬렉션 뷰식 "로컬 텍스트
필터"(이미 로드된 항목 부분일치)를 쓰면 **현재 20행 페이지 안에서만** 걸러진다 — 다른 페이지에 있는 매치를
"결과 없음"으로 **오인**하게 만든다(spec 097이 정리한 "로컬 필터 vs 서버 검색" 구분의 반대편 사례). 따라서
검색은 **서버 쿼리 파라미터**로 추가해 전체 스코프(페이징 이전)에서 매칭해야 정직하다.

## 2. 설계 결정

**결정 A — 서버측 `q` 파라미터, 메타데이터 3컬럼 OR ilike.** `GET /sessions`에 `q: str | None` 추가.
검색 대상(전부 `Session` 컬럼 — **조인 불필요**, 비정규화 `agent_name` 활용):
- `Session.session_id` (표시되는 "sess_..." 식별자 = 프런트 `s.id`)
- `Session.user_id` (대화 유저)
- `Session.agent_name` (에이전트 표시명)

predicate = `or_(session_id ilike, user_id ilike, agent_name ilike)`. 빈/공백 `q`는 무시(필터 미적용).

**결정 B — status 필터와 AND, 페이징 이전에 적용.** `q`는 기존 `base` 쿼리(own-scope·status·agent_id가
이미 얹힌)에 **AND**로 추가 → count·items 양쪽에 자동 반영(페이징 전 전체 스코프 매칭). status 버킷과
독립적으로 결합(예: "error" 버킷 + "sess_ab" 검색).

**결정 C — ilike 와일드카드 이스케이프.** 사용자가 `%`·`_`·`\`를 입력하면 리터럴로 취급(`escape="\\"` +
`\`·`%`·`_` 치환) — 과매칭/오라클 방지.

**RBAC (체크리스트 트리거됨 — 세션=유저별 데이터, `user_id` 컬럼, `_own_scope` 헬퍼):**
1. **입구 열거**: 자원(세션)을 읽는 입구 = 목록 `GET /sessions` **하나**(item/detail은 `_get_session_or_404`가
   별도 게이트, 이 스펙 미변경). 검색은 **읽기 전용**, 생성/수정/삭제 입구 없음.
2. **입구별 소유권 (읽기)**: `q` predicate는 `base`에 **AND**로 얹힌다. `base`는 이미 비-admin이면
   `Session.user_id == own`을 **SELECT WHERE에** 갖는다(067) → 스코프 밖 세션은 **로드조차 안 됨**.
   검색이 소유권 경계를 **넓힐 수 없다**(AND는 집합을 좁히기만 함). fetch-then-check 아님.
3. **단일 헬퍼**: 스코프 판정은 기존 `_own_scope` 그대로(드리프트 0). 검색은 스코프 로직 미변경.
4. **존재 비노출**: 스코프 밖 세션은 검색 매칭 이전에 `base`에서 제외 → 타인 세션 존재가 검색으로
   **누설 안 됨**(열거 오라클 없음). 배지 `counts`도 067 스코프 그대로.
5. **검증 사다리 3런**: ① 단위(검색어가 3컬럼 매칭·빈 q 무시·이스케이프), ② **실 인프라 통합**
   (비-admin이 *타인* 세션과 매칭되는 검색어를 넣어도 빈 결과 = own-scope 홀드), ③ **적대 타자(codex)**.
6. **자가-잠금 핀**: 비-admin이 *본인* 세션을 검색어로 정상 조회 가능(조임이 정당 접근 차단 안 함).

## 3. 구현

- `packages/api/src/api/sessions.py`: `list_sessions`에 `q: str | None = None` 파라미터 + 이스케이프 후
  `base = base.where(or_(...ilike...))`. `from sqlalchemy import or_` 추가. 도크스트링 갱신.
- `admin/src/api.ts`: `listSessions` params에 `q?: string` 추가, 존재 시 `q` 쿼리 세팅.
- `admin/src/admin/views/SessionsView.tsx`: 검색 `Input`(clearable, 디바운스 ~300ms) 추가, `q` 상태,
  `q` 변경 시 page=1 리셋, `listSessions({status, q, ...})` 전달. status Radio 옆 배치. placeholder
  "세션 ID·유저·에이전트 검색".

## 4. 완료 조건 (측정가능) — 전부 충족 ✅

- [x] **동작**: 브라우저(`tests/browser/verify-session-search-098.mjs`) — 마커 입력 시 서버 재조회로
      해당 2건만(`after_codes==[zz098_a,zz098_b]`), clear 시 전체 목록 복귀(19건), 매칭없음→0건+
      "조건에 맞는 세션이 없습니다" empty 문구. 검색창 존재. 스샷 `/tmp/098-search.png`. 4/4 PASS.
- [x] **서버 스코프(정직)**: `q`가 `base`(페이징 이전)에 AND → total·counts 검색 반영(rung① [5]
      `q=MARKERID total==1`). 로컬필터 아님(서버 재조회 = 전체 스코프).
- [x] **RBAC 3런**: ① 단위(`verify_098` [1~6]: 3컬럼·OR·대소문자·빈/공백q·status AND·이스케이프),
      ② 통합([7] 비-admin이 타인 세션과 agent_name 공유 검색→foreign 누출 0 / [8] 본인 세션 검색→
      조회됨=자가잠금 핀), ③ **codex 적대: no P0/P1**(own-scope AND 위치·이스케이프 순서·SQLi 바인딩·
      프런트 stale-가드·공백 파리티 명시 확인). 14 단언 ALL PASS.
- [x] **회귀 없음**: `tsc --noEmit` EXIT 0, `verify_098_session_search.py` ALL PASS, 기존 status/
      agent_id/페이징 무영향(빈 q → 회귀 0 단언 [3]).

## 5. 알려진 잔존 / 비목표

- **메시지 본문 전문검색 비목표**(사용자 선택). 향후 필요 시 pg trigram/FTS + EXISTS 서브쿼리로 별도 스펙.
- 검색 디바운스는 프런트 UX(백엔드는 매 요청 처리). 대량 세션 시 `session_id`/`user_id` 인덱스 활용,
  `agent_name`은 인덱스 없어 ilike full-scan 가능(현 규모 허용, 대량화 시 인덱스 검토).
