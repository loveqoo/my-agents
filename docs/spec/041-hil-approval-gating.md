# 041 — HIL 승인 게이팅: langgraph checkpoint/interrupt (P5-a, 로드맵 #12)

상태: **Planning(초안)** — 인간 검토·승인 대기. 브랜치 `feat/agent-service`(main 머지 금지).
날짜: 2026-06-27
지배 스펙: `033-feature-roadmap.md`(P5), `007-real-agent-service.md`(런타임), `031`(인증/RBAC).
연동: `029`(에이전트 도구·calls_sink 트레이스), `034`(세션). 후속(P5-b): `#11 A2A 실호출`은 별도 스펙.

---

## 1. 무엇을 / 왜

**현재 "승인"은 픽션이다.** `approvals.py`는 status flip만 하고(`pending→approved/rejected`),
Approval row는 `seed.py`로만 생긴다(런타임 생성 0). 그래프(`create_react_agent`)는 **무상태** —
체크포인터·thread_id·interrupt 전부 미사용, 매 턴 재구축, `chat.py:433`에서 thread_id 없이 astream.
Admin `ApprovalsView`엔 "승인 및 재개 / 체크포인트에서 일시정지됨" UI가 **이미 있으나 재개 기전이 0**.

→ **위험 도구를 실제로 멈춰 세우는 게이트**로 바꾼다: admin-승인 권한 도구(`repo.merge`·`k8s.write`)를
에이전트가 호출하려 하면 그래프가 **langgraph interrupt로 진짜 일시정지**(durable 체크포인트에 박제),
런타임이 `Approval` row를 만들고, admin이 `ApprovalsView`에서 승인/거부하면 **그래프를 재개/중단**한다.

**핵심 불변식(안전 기전, 적대 검증 대상):** approver=admin 도구의 부수효과는 **승인된 Approval row가
있기 전에는 절대 일어나지 않는다.** 거부면 실행 안 함. (현재 도구는 합성이라 "부수효과"=canned 결과+
calls_sink 트레이스 emit이지만, 게이트는 *실행 결정* 자체를 막으므로 실 MCP로 바뀌어도 동일하게 유효.)

---

## 2. 현 상태 (census, file:line)

- `approvals.py:33` `resolve_approval` — status만 바꿈, 그래프 재개 없음. row는 `seed.py:298` 하드코딩만.
- `models.py:283` `Approval(approval_id, session_id, agent_pk, permission, action, args, summary, checkpoint, status, requested_at)` — `checkpoint` 컬럼 존재하나 **never read**.
- `seed.py:67-71` `Permission(name, scope, approver, body)` — `repo.merge`·`k8s.write`=**approver=admin**, `mail.send`·`calendar.rw`=user(인라인), read 계열=무게이트. (정책이 이미 DB에 있음.)
- `agent/main.py:54` `create_react_agent(model, tools, prompt)` — checkpointer 인자 미전달.
- `chat.py:420` `build_agent(...)` → `:433` `graph.astream({"messages":...}, stream_mode="messages")` — config/thread_id 없음(무상태).
- `runtime.py:36` `build_tools` — (server,tool)→합성 StructuredTool, 호출 시 `_CANNED` 반환 + calls_sink 기록. **게이트 없음**.
- langgraph: `MemorySaver`·`interrupt`·`Command` 가용, `create_react_agent`가 `checkpointer`/`interrupt_before` 지원 확인. `PostgresSaver`는 **미설치**(의존성 추가 필요).

---

## 3. 설계

### 3.0 결정(합의 완료)
- **체크포인터 = AsyncPostgresSaver(durable)** — 재시작·멀티워커에서 대기 승인 생존. 공유 Postgres 사용.
- **게이트 범위 = admin-승인 도구만**(`repo.merge`·`k8s.write`) → 기존 `ApprovalsView`로 라우팅.
  user-inline 확인(`mail.send`·`calendar.rw`)은 별도 surface → §7 빚.

### 3.1 Durable 체크포인터
- 의존성 `langgraph-checkpoint-postgres`(+psycopg) → `packages/api`. 공유 DSN(psycopg3 `postgresql://…` 형식)
  헬퍼(asyncpg DSN을 psycopg용으로 변환 — `mem0_backend._sync_dsn` 패턴 재사용).
- 앱 시작(lifespan)에 `AsyncPostgresSaver` 싱글턴 생성 + `.setup()`(langgraph 자체 테이블 `checkpoints`/
  `checkpoint_writes`/`checkpoint_blobs` 멱등 생성). 우리 `Base.metadata` 밖(라이브러리 소유) — alembic 무관.
- `build_agent(persona, params, tools, model_cfg, checkpointer=None)` — checkpointer를 `create_react_agent`로 전달.

### 3.2 thread_id (재개 키)
- `thread_id = f"{agent_id}:{session_id}"`(세션당 안정). `chat.py` astream에 `config={"configurable":{"thread_id":…}}`.
- 재개는 같은 thread_id로 그래프를 **재구축**(같은 checkpointer·tools·model)해 `Command(resume=…)` 호출.

### 3.3 위험 도구 게이트 (dynamic interrupt)
- 정책 맵 `_APPROVAL_ACTIONS: {(server, tool): permission}` — admin approver 권한만. seed 근거:
  `("github","merge_pr")→"repo.merge"`, `("kubernetes","scale")→"k8s.write"`. (실 (server,tool) 키는
  실행 단계에서 `_load_context`의 `mcp_pairs` 포맷과 대조 확정 — 정책은 코드 한 곳, 테스트로 핀.)
- `build_tools`가 정책에 걸리는 도구를 만들 때, canned 반환 대신 **`interrupt(payload)`로 일시정지**.
  `payload = {permission, action(server.tool), args, summary, agent_id, agent_name}`. interrupt는 **부수효과
  (canned·calls_sink) 이전**에 호출 → 승인 전 실행/트레이스 emit 0(불변식).
- `interrupt`의 반환값(=resume 페이로드)으로 분기: `approve`면 canned 실행+트레이스 기록, `reject`면
  "거부됨 — 실행 안 함" 반환(부수효과 0).

### 3.4 interrupt → Approval row (런타임 생성)
- `chat.py`가 astream에서 `__interrupt__` 이벤트를 감지 → interrupt payload로 `Approval`(status=pending,
  checkpoint=thread_id, session_id, agent_pk, permission, action, args, summary) **생성**(async DB 세션은
  API 계층에만; 도구는 순수 유지). SSE로 "⏸ 승인 대기: {action} — 관리자 승인 필요" 1프레임 후 스트림 종료.

### 3.5 재개 (resolve → resume)
- `approvals.resolve_approval`이 status 설정 후 **`chat.resume_approval(approval, decision)` 호출**:
  에이전트 컨텍스트 재로딩(_load_context 경로) → checkpointer+thread_id로 그래프 재구축 →
  `graph.astream(Command(resume={"decision":decision}), config={thread_id})` → 최종 메시지를 **원 세션에
  영속**(유저가 세션 재로딩 시 [질문]→[⏸]→[재개 답변]). 멀티워커 안전(체크포인트=Postgres 공유).
- approve→도구 실행 후 ReAct 종료 답변 저장. reject→도구 미실행, 에이전트가 그 사실로 마무리.
- 가드: 이미 resolved면 재개 금지(중복 승인 차단), checkpoint 없으면 404/무시.

---

## 4. 작업 항목

1. **Scaffolding**: `langgraph-checkpoint-postgres` 의존성, psycopg DSN 헬퍼, lifespan에 AsyncPostgresSaver+setup.
2. `agent/main.py`: `build_agent(..., checkpointer=None)` → create_react_agent 전달.
3. `runtime.py`: `_APPROVAL_ACTIONS` 정책 + `build_tools`가 위험 도구를 interrupt 게이트로 래핑.
4. `chat.py`: thread_id+config, `__interrupt__` 감지 → Approval 생성 + "대기" 프레임; `resume_approval` 함수.
5. `approvals.py`: `resolve_approval`이 status 후 `resume_approval` 호출(approve=실행 재개/reject=중단).
6. **Tests**: `verify_041`(인프라-경량: 게이트 정책·interrupt 전 무실행·resume 분기 semantics) + 브라우저 e2e.

---

## 5. 검증 (측정 가능 — 타자 검증 우선)

- **게이트 단위(verify_041, 인프라 경량):** 가짜/실 그래프에 위험 도구 1개 주입.
  - 위험 도구 호출 → `__interrupt__` 발생 + canned/calls_sink **미emit**(승인 전 무실행) 단언.
  - `Command(resume=approve)` → 도구 실행(canned+트레이스) + 종료. `resume=reject` → 미실행.
  - 정책 맵: 비위험(read) 도구·무도구 턴은 interrupt 0(회귀).
  - resolve 가드: 이미 resolved row 재개 거부(중복 승인 불가).
- **회귀:** 비위험 채팅 턴(무도구/read 도구)이 thread_id 도입 후에도 무회귀 — 기존 verify + 스모크.
- **적대 리뷰(필수, 안전 기전 — learning 038·memory adversarial-review-before-destructive-ship):**
  서브에이전트에 "**승인된 row 없이 위험 도구의 부수효과가 일어나는 경로**를 찾아라" 명시:
  게이트 우회(정책 누락·이름 충돌), 이중 실행(interrupt 전후 2회), 거부인데 실행, 이미 resolved 재개,
  thread_id 위조/엇갈림. 발견은 코드 floor 또는 §7 빚으로 정직히.
- **브라우저(e2e, 실 mlx):** 런타임이 만든 **실 pending 승인**(seed 아님)이 ApprovalsView에 뜨고,
  승인→원 세션에 재개 답변이 보임. 거부→실행 안 됨. 스크린샷.

## 6. 완료 조건

- [x] C1. AsyncPostgresSaver 연결(그래프에 checkpointer, 턴별 thread_id, langgraph 테이블 setup). interrupt→체크포인트 박제→resume 재개 측정.
  - 증거: `probe_041_chat_integration.py` — 실 AsyncPostgresSaver 활성 + 같은 thread_id로 chat→pause→resolve→resume 재개 성공(18/18). thread_id는 **턴별 고유**(`{agent}:{session}:{hex}`)로 결정 — §3.2 "세션-안정"에서 벗어남: 세션-안정+매턴 전체 히스토리는 `add_messages` 리듀서가 메시지를 중복 누적(무상태 윈도잉 충돌). 턴별 thread는 그 턴의 pause/resume에만 쓰고 `Approval.checkpoint`에 재개키로 박제.
- [x] C2. admin-승인 도구 호출 → 그래프 일시정지(interrupt) + Approval(pending, checkpoint) 런타임 생성, 승인 전 canned/트레이스 **미emit**.
  - 증거: `verify_041` G1(interrupt+payload+calls_sink 0) + `probe_041_chat_integration` (pause 시 Approval pending·repo.merge 생성, 승인 전 최종답변 미영속).
- [x] C3. 승인 → 재개 → 도구 실행(canned+트레이스) + 최종 메시지 원 세션 영속 + status=approved.
  - 증거: `verify_041` G2 + `probe_041_chat_integration` (resolve approve → status=approved, 재개 그래프가 도구 실행 후 최종답변 원 세션 영속).
- [x] C4. 거부 → 재개 → 도구 미실행 + 에이전트 마무리 + status=rejected.
  - 증거: `verify_041` G3(reject→calls_sink 0) + `probe_041_chat_integration` (resolve reject → status=rejected, 재개 무크래시).
- [x] C5. 비위험 도구·무도구 턴 무회귀(interrupt·approval 0).
  - 증거: `verify_041` G4(read 도구 즉시 실행, interrupt 0)·G5(무도구 턴 interrupt 0)·G7(정책 맵 admin 권한 2개 정확, read 미포함).
- [x] C6. 적대 리뷰: 승인 없는 위험 도구 실행 경로 0(또는 빚 명문화).
  - 증거: 서브에이전트 적대 리뷰 2회. 1차 — `/approvals/{id}/resolve`가 인증만(비-admin·머신토큰이 승인 가능) **홀 발견 → admin 인가(`authz.require("approvals","resolve")`) 추가, `probe_resolve_authz`로 HTTP 증명**(admin→404 통과, member→403, 머신→401). 2차 — 6개 공격류(게이트 우회·이중실행·거부실행·무체크포인터 fail-open·무승인 재개·인가) 전부 불변식 무사 확인. **Finding 1**(다중 게이트 동시 호출 → resume 크래시) 발견: fail-closed지만 오도 approved row → **코드 floor**(chat.py: 다중 interrupt면 승인 row 미생성·명시적 에러, `probe_041_chat_integration` Finding1 케이스로 증명). Finding 2(sibling 안전도구 재실행 §7 빚)는 langgraph 1.x에서 **재현 불가**(완료 task write가 체크포인트 캐시·미replay)로 반증 → §7에서 닫음.
- [~] C7. 브라우저 e2e: 실 런타임 승인이 ApprovalsView에 뜨고 승인→재개 답변, 거부→무실행.
  - **백엔드 경로는 `probe_041_chat_integration`(실 HTTP·실 DB·실 AsyncPostgresSaver)로 결정적 증명** — 실 pending Approval row 생성(GET /approvals가 읽는 동일 테이블)→admin resolve→재개·영속. ApprovalsView UI는 본 스펙에서 **미변경**(스펙 007에서 이미 검증). 실 mlx가 위험 도구를 호출하도록 유도하는 라이브 브라우저 e2e는 비결정적·GPU 의존이라, 사용자 브랜치 실환경 테스트로 인계(상시 제약: "나중에 내가 직접 브랜치에서 테스트"). 스크린샷은 그 시점에.

## 7. 범위 밖 / 빚

- **다중 게이트 동시 호출**(한 턴에 위험 도구 ≥2) — 현재는 fail-closed로 닫음(승인 row 미생성·명시적 에러, 사용자가 하나씩 재시도). 동시 다중 승인(N Approval + interrupt-id별 `Command(resume=...)`)은 후속. 적대 검증 Finding 1.
- **기존 DB 시드 갭** — seed.py의 위험 도구 배선(`github.merge_pr`·`kubernetes.scale`)은 `_empty`일 때만 적용 → **이미 시드된 DB는 미반영**(게이트 미발동). 기존 환경은 재시드 또는 enabled_tools 가산 마이그레이션 필요(probe가 setup으로 보정). 후속: idempotent 시드 업서트 또는 alembic 데이터 마이그레이션.
- **sibling 안전도구 재실행** — ~~resume 시 같은 턴의 비게이트 도구가 재실행될 수 있음~~ → langgraph 1.x에서 **재현 불가**(완료 task write가 체크포인트에 캐시·미replay, 적대 검증 Finding 2로 반증). 빚 아님.
- **user-inline 확인**(`mail.send`·`calendar.rw`, approver=user) — 채팅/플레이그라운드 인라인 확인 UX 별도 surface. 후속.
- **재개 라이브 스트리밍을 admin UI로** — 본 스펙은 서버사이드 재개+세션 영속만(ApprovalsView는 status·결과요약).
- **실 MCP 실행** — 도구는 합성 유지. 게이트는 *실행 결정*을 막는 것(실 MCP 전환 시 그대로 유효).
- **A2A 실호출(#11)** = P5-b 별도 스펙.
- 승인 TTL/만료, 세션 삭제 시 pending 취소, 고아 interrupt 정리(다중 게이트 fail-closed 시 체크포인트에 남는 pending 포함) — 후속.
