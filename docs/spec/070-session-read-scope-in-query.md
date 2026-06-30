# 070 — 세션 읽기 라우트 owner 스코프를 쿼리에 융합 (067 P3-1 타이밍 오라클 봉합)

## 배경 / 문제

067이 세션 읽기 라우트(detail/messages/end)에 유저별 스코핑을 걸었으나, 구현이 **fetch-then-check**다:
`_get_session_or_404`가 `session_id`만으로 행을 *먼저 로드*하고 `_visible_or_404`가 *사후 거부*한다.
타인-존재행(로드 성공 후 404)과 부재행(즉시 404)이 **다른 코드 경로**를 타 — 상태/본문 오라클은
없으나 *타이밍* 측면채널이 남는다(retrospect 056 [P3-1], 비블로킹으로 이월).

= 069 체크리스트 항목 2(a)의 정확한 위반: *"읽기는 owner 스코프를 SELECT WHERE에 밀어넣어 거부행을
로드조차 안 함. fetch-then-check는 그 자체가 잔존 타이밍 오라클."* — **이 스펙은 069 체크리스트의
첫 적용 사례**다.

## 목표

owner 스코프를 *쿼리 자체*에 융합해 타인-존재행과 부재행을 **동일한 단일 쿼리에서 둘 다 `None`**으로
만든다 → 동일 404 경로 → **앱(ORM 로드·직렬화) 계층** 타이밍 측면채널 제거. (저장계층은 §적대 검증
참고 — 단일화로 *축소*되나 인덱스 프로브 델타가 잔존, P2로 별도 기록.)

## 비목표

- 067/068의 *기능* 경계(누가 무엇을 보나)는 그대로 — 이건 *구현 방식*만 바꾸는 무행동변경 리팩터.
- chat resume(068)·approvals·memory의 fetch-then-check는 범위 밖(각자 별도 작업).

## 위협 모델

- T-타이밍: member가 *존재하지만 자기 것이 아닌* session_id와 *부재* session_id의 응답 *시간차*로
  숨은 세션의 존재를 추론(열거 오라클의 타이밍 변종). 상태(둘 다 404)·본문은 이미 동일.
- 무회귀: admin/머신(own=None)은 전체 접근 유지. 본인 세션 접근·종료는 그대로.

## 설계

### D1 — `_get_session_or_404(session, session_id, own=None)`
`own`이 None이 아니면 쿼리에 `.where(Session.user_id == own)`을 더한다. 타인행·NULL-owner행·부재행이
*모두* `scalar_one_or_none() → None` → 단일 404. docstring에 가시성 게이트가 쿼리에 융합됨을 명시
(거부행 로드 안 함 = P3-1 봉합). own=None이면 무스코프(admin 전체).

### D2 — 세 라우트 한 줄화
detail/messages/end: `s = await _get_session_or_404(session, session_id, _own_scope(principal))`.
`_visible_or_404` 호출 3곳 제거.

### D3 — `_visible_or_404` 삭제
미사용화되므로 함수 제거. 가시성 은폐 책임은 D1 헬퍼로 단일화(체크리스트 항목 3 — 단일 헬퍼).

## 검증 사다리 3런 (비겹침 — 069 항목 5)

1. **단위(verify_070_scope.py)**: own 스코프가 WHERE에 들어가 타인 session_id→404·본인→객체 반환,
   타인-존재행과 부재행이 *동일 경로*(둘 다 None). admin(own=None)은 전체 반환.
2. **라이브(verify_070_live.py, seed+restart)**: 유저 A·B 세션 시드 → B가 A의 session_id로
   detail/messages/end 호출 시 전부 404, 본인 세션은 200/종료 성공. admin 전체 접근 무회귀.
3. **적대 codex**: 여집합 — 타이밍 외 누설(에러 메시지 차이·end commit 부수효과·admin 무회귀 깨짐·
   다른 라우트 누락) 탐색.

## 적대 검증 결과 (codex challenge, 반영 완료)

적대 타자가 입구 전수 추적(`sessions.py`·`chat.py`·`models.py`·`approvals.py`·`batch/jobs.py`) + 단위/라이브
재실행 후 **P1 없음** 확정:
- end 변이는 스코프 읽기 *뒤에만* 발생 → UPDATE/commit이 WHERE로 게이트됨(타인 세션 종료 0).
- admin/머신(own=None) 전체 접근 무회귀, member 자기접근 `str(principal.id)`, NULL-owner는 member에게
  read/end 모두 숨겨짐(067 등가).
- `Session.session_id`를 public id로 읽는 입구는 `sessions.py`·chat resume 둘뿐 — 추가 누락 입구 없음.

**[P2] 저장계층 타이밍 잔존(비차단, 기록):** 앱 파이썬 경로는 단일화됐으나 `session_id`에 *독립* unique
인덱스(`models.py`)가 남아, member 쿼리 `WHERE session_id=:id AND user_id=:own`에서 Postgres가 그
인덱스로 타인-존재행을 잡아 `user_id`에서 거부 vs 부재행은 인덱스 미스 → 저장계층에서 타인-존재 vs
부재 시간차가 *축소되나 잔존*(구 fetch-then-check보다 작음). chat resume(`chat.py`)도 동형.
- **처방(별도 하드닝)**: 스코프 읽기용 복합 인덱스 `(user_id, session_id)`(chat은 `(user_id, agent_pk,
  session_id)`)를 더해 단일 프로브화하고 `EXPLAIN (ANALYZE, BUFFERS)`로 타인-존재 vs 부재 동일 경로 확인.
- **비차단 사유**: B-tree 노드 접근 델타로 네트워크·쿼리 지터에 묻혀 외부 member가 실측 불가. 067이
  P3-1을 비차단 이월한 것과 동일 계층. 이 스펙(무행동변경 리팩터)의 범위 밖 — 마이그레이션+EXPLAIN은
  별도 스코프. learning 073에 *앱계층 단일화≠저장계층 봉합* 일반화로 자산화.

## 완료 조건

- [x] detail/messages/end가 단일 스코프 쿼리로 거부행을 로드하지 않음(`_visible_or_404` 제거).
- [x] 단위(verify_070_scope.py 12체크)·라이브(verify_067_live.py 23체크) 그린, admin 무회귀.
- [x] 적대 codex가 잔여 P1 없음 확인. P2(저장계층 인덱스 프로브 델타)는 위 §에 반영, 복합인덱스 하드닝은 별도.

## 연결

- 봉합 대상: 067 D4, retrospect 056 [P3-1]. 체크리스트: spec 069 항목 2(a)/3/5.
- learning: 068(404-vs-403 오라클), 072(메타 가드 — 체크리스트 적용).
