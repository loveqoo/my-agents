# 073 — 세션 읽기 저장계층 타이밍 봉합: owner-선두 복합 인덱스 + EXPLAIN 측정 (070 P2)

## 배경

070이 세션 읽기 게이트를 **앱(파이썬·ORM) 계층**에서 단일화했다(owner 스코프를 SELECT WHERE에 융합 →
타인-존재행·부재행 모두 `None`). 그러나 적대 codex가 **저장계층 잔존**을 짚어 P2로 이월:

- `sessions.session_id`에 **단독 unique 인덱스**가 남아 있다(`models.py:251`).
- member 읽기 쿼리 `WHERE session_id=:id AND user_id=:own`에서 Postgres가 그 단독 인덱스로
  **타인-존재행을 물리적으로 잡고(heap fetch)** `user_id`에서 거부 vs 부재행은 인덱스 미스(heap fetch 없음)
  → **타인-존재 vs 부재의 buffer 접근 델타 = 타이밍 측면채널**(070 앱계층 봉합 후에도 *축소되나 잔존*).
- chat resume(`chat.py:223-229`)도 동형: `WHERE session_id AND agent_pk AND user_id`.

근거 자산: learning 073(앱계층 단일화≠저장계층 봉합), spec 070 §적대 검증 [P2], retrospect 058.

## 목표 (완료 조건 — 측정 가능)

**owner를 선두로 한 복합 인덱스**를 추가해, member 읽기 시 타인-존재행이 **인덱스 진입 단계에서 곧장
미스**(부재행과 동일)가 되도록 — heap fetch 유무 델타를 제거한다.

- `(user_id, session_id)` — sessions.py `_get_session_or_404` member 경로.
- `(user_id, agent_pk, session_id)` — chat.py resume member 경로.

원리: owner가 선두 컬럼이면 타인 행은 `(내_user_id, 그_session_id)` 조합이 인덱스에 없어 부재행과
물리적으로 동일한 미스가 된다(타인의 행은 *타인의 user_id* 아래 있음).

## 핵심 — 인덱스 추가만으론 끝이 아니다 (측정이 본질)

`session_id` 단독 unique는 극도로 selective(1행)라, **플래너가 복합 대신 그 단독 인덱스를 고를 수
있다.** 그러면 봉합이 무효다. 따라서 완료 조건은 "인덱스가 존재한다"가 아니라 **"EXPLAIN으로 member
쿼리가 타인-존재행·부재행에서 동일 인덱스·동일 buffer 접근을 보인다"**이다(learning 073 항목 2: 자가
단정 금지, `EXPLAIN (ANALYZE, BUFFERS)`로 *측정*).

### 측정 결과에 따른 분기

- **(기대) 플래너가 복합을 선택** — 복합이 WHERE의 *모든* 조건(user_id+session_id)을 커버하므로
  단독(session_id만 커버, user_id는 heap 필터)보다 선호될 공산이 큼. → EXPLAIN으로 확정하면 종료.
- **(대비) 플래너가 여전히 단독 unique를 선택** — 그러면 델타 잔존. 후속 조치 후보를 *측정 후* 결정:
  (a) 통계/cost 재검토, (b) `session_id` 단독 인덱스를 유지하되 member 경로 보강 방안 재설계.
  단독 unique 자체는 **제거 불가**(session_id는 전역 unique 보장 필요 — get-or-create flush가 의존,
  `chat.py:288`·`models.py:251`). 이 분기에 들어가면 P2를 재-기록(정직)하고 사용자와 협의.

## 설계

### D1 — alembic 마이그레이션 (head `e1f2a3b4c5d6` 위에)
`op.create_index(op.f('ix_sessions_user_id_session_id'), 'sessions', ['user_id', 'session_id'])` +
`op.create_index(op.f('ix_sessions_user_id_agent_pk_session_id'), 'sessions',
['user_id', 'agent_pk', 'session_id'])`. unique=False(복합은 조회 경로 단일화용, uniqueness는 기존
session_id 단독 unique가 계속 보장). downgrade는 두 인덱스 drop. 멱등 고려.

### D2 — models.py 인덱스 선언 동기화
ORM 모델에도 `__table_args__`로 두 복합 인덱스를 선언(마이그레이션과 모델 drift 방지 — 새 환경
`create_all`/스키마 비교 시 일치). 컬럼 정의는 불변(무행동변경 — 인덱스만 추가).

### D3 — 측정 스크립트 `tests/verify_073_explain.py`
유저 A·B 세션 시드 → B 관점(own=B)으로 (i) A의 session_id(타인-존재), (ii) 없는 session_id(부재)를
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`로 실행 → **동일 인덱스명·동일 heap/buffer 접근**인지 단언.
resume 쿼리도 동형 측정. 측정값을 출력(자가 단정 아닌 실측 로그).

## RBAC 체크리스트 적용 여부
**부분 적용** — `user_id` 소유권 컬럼·`_get_session_or_404` 소유 헬퍼가 닿으므로 트리거됨. 단 이 작업은
*새 입구 추가가 아니라 070이 닫은 읽기 게이트의 저장계층 보강*이라 입구 집합은 070에서 이미 닫힘
(재열거 불요). 적용 항목: **5③ 적대 rung(여집합)**, **5② 실 인프라(seed+EXPLAIN 측정)**, 항목 2는
저장계층 동일성으로 한정. 자가-잠금 핀(6): 본인 세션 정상 조회·admin 무회귀 측정 포함.

## 검증 사다리 3런 (비겹침)

1. **단위/스키마**: 마이그레이션 up/down 멱등, 두 복합 인덱스가 `pg_indexes`에 존재, 모델 `__table_args__`
   와 일치. 기존 verify_070_scope 그린(무행동변경).
2. **실 인프라 측정** (verify_073_explain): seed → EXPLAIN으로 타인-존재 vs 부재 **동일 경로 실측**
   (이 작업의 *고유* rung — 단위·적대가 못 보는 플래너 선택을 측정). + verify_067_live 무회귀.
3. **적대 codex**: 여집합 — (a) 플래너가 복합을 *정말* 고르나(아니면 봉합 무효), (b) 인덱스 추가가
   get-or-create/admin(own=None) 경로·쓰기 성능에 회귀, (c) agent_pk 순서·NULL user_id 행 처리,
   (d) downgrade 가역성, (e) "측정으로 동일"이 특정 데이터 분포에만 성립하는 건 아닌지.

## 적대 검증 결과 (rung 3 — codex challenge)

codex가 P1×2·P2×3을 냈다. 수정(복합 인덱스)·앱계층 게이트는 옳고 **새 probe 입구는 없음**을 확인(아래
#5), 지적은 전부 *검증이 주장보다 약함*에 집중 → 측정 강화로 봉합.

| # | codex 지적 | 판정 | 처분 |
|---|---|---|---|
| P1-1 | 측정이 N_FILL=600 한 분포에서 플래너가 복합을 골랐을 뿐, **강제**가 아님. 운영 분포(소규모→seq, 통계 드리프트→solo unique 회귀) 시 델타 잔존 가능 | **유효** | 정직 재-기록(아래 잔존). + 반증 데모로 인과 입증 |
| P1-2 | rows_removed=0만 단언, 타이밍 실제 지표인 **buffer 동등 미단언**. heap_touch 계산해놓고 버림 | **유효** | `_summarize`에 `total_blocks(shared_hit+read)` 추가, R1·R2/S1·S2 **buffer 동등 단언**. 실측 2==2 |
| P2-3 | resume 단언이 `startswith("ix_sessions_user_id")` → `(user_id,session_id)`로도 통과, 새 `(user_id,agent_pk,session_id)` **미입증** | **유효** | `RCOMP in s1["indexes"]`로 **특정 단언**. 실측 선택 확인 |
| P2-4 | 마이그레이션 비멱등(plain create/drop) — 재실행·부분드리프트 시 실패 | **유효** | `if_not_exists`/`if_exists`. 부분드리프트(한 인덱스 선존재) upgrade 수렴 실증 |
| P2-5 | 인덱스 2개 추가의 쓰기 비용 미측정 | **수용(잔존)** | sessions는 저빈도 쓰기(대화당 1 insert + 가끔 status/user_id update), 읽기-보안 > 한계 insert 비용. 의식적 트레이드오프로 기록 |

**측정으로 확정된 인과(반증):** 복합을 트랜잭션 내에서 가려 플래너에게 solo unique를 강제하면 타인-존재
F1=3블록(heap-fetch+1, removed_by_filter=1) vs 부재 F2=2블록 → **델타 1블록 재출현**. 복합이 있으면
R1=R2=2블록(동등). 즉 복합 인덱스가 봉합의 *실제 원인*이고, 위 buffer-동등 단언이 우연이 아님(델타에
민감)을 반증으로 확정.

**정직한 잔존(P1-1):** 이 봉합은 플래너 **선택**이지 **강제**가 아니다. 측정된 현실 분포(복합이 WHERE
모든 컬럼 커버 → 비용 경쟁력)에서 플래너가 복합을 고르고 buffer가 동등하나, 병리적 통계/소규모 테이블에서
solo unique로 회귀하면 델타가 돌아온다(반증이 그 경우를 실측). **완전 강제하려면 solo unique 제거가
필요하나 전역 uniqueness(get-or-create flush)가 막는다**(스펙 §대비 분기). 추가로 `session_id`는
128bit 시크릿(`secrets.token_hex(16)`)이라 공격자가 유효 id를 *추측해 probe*할 수 없어 실 악용성은
극히 낮다(이 작업은 심층방어 경화). → P2는 **봉합 완료가 아니라 "감축+측정+정직 잔존"**으로 기록.

## 완료 체크
- [x] D1 마이그레이션(복합 인덱스 2개, up/down) — `if_not_exists`로 멱등, 부분드리프트 수렴 실증
- [x] D2 models.py `__table_args__` 동기화(drift 0 — 마이그레이션 DDL과 동일 2 인덱스)
- [x] D3 EXPLAIN 측정 그린 — 타인-존재 vs 부재 **동일 인덱스·buffer 총블록 동등**(복합 선택 실측) + 반증
- [x] verify_070_scope / verify_067_live 무회귀(자가-잠금 핀: 본인접근·admin 무회귀)
- [x] 적대 codex triage 기록(위 표). 플래너 **선택**(강제 아님) — 정직 잔존 명시(P2 = 감축+측정)
