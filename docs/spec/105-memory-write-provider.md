# 105 — 능력 브로커 kind 확장: Memory **write** provider (Phase 2, 첫 부수효과·승인 게이트 능력)

## 배경 / 왜

104가 메모리 **읽기**(`memory:user`)를 per-user 소유 능력으로 붙였다. 이 스펙은 메모리 **쓰기**(add)를
붙인다 — 브로커 최초의 **부수효과(비가역 지속 쓰기) 능력**이라 **승인 게이트**(두 게이트 중 승인 O)가
처음으로 실제 발화한다.

**핵심 위험(learning 031·spec 051):** 과거 에이전트 자가기록 도구에서 **LLM이 사용자의 "이거 기억해"를
도구 프롬프트의 금지보다 우선**해 PII를 agent_id(교차유저 회상) 스코프에 저장, 다른 유저 세션에서
새어나왔다. 교훈은 명확했다 — **도구 프롬프트의 규율은 격리 경계가 아니다. 진짜 보장은 프롬프트가
아니라 구조(승인 게이트)로.** 이 스펙은 그 구조를 정확히 놓는다.

## 핵심 설계 — 두 개의 구조적 방어

### 1. 쓰기 축 = user_id(자기)만, principal 바인딩 (누출 차단)
- 쓰기는 **실행 주체 자신의** user_id 스코프에만(`{"user_id": self._user_id}`). **agent_id에 절대 안 쓴다**
  (051이 막은 교차유저 누출 축). user_id는 104처럼 **cap_id·args가 아니라 런타임 principal에서 도출** —
  능력 이름으로 남의 기억을 가리킬 방법이 없다(교차유저 쓰기 *구조적* 불가). 자기 기억에 쓰는 것은
  정의상 교차유저 누출이 불가능하다(스코프가 자기).

### 2. 승인 게이트 (부수효과 사람 확인)
- 쓰기는 **항상 승인 필요**(`approval_for`가 **절대 None을 안 돌림** — 읽기 provider들과 정반대).
  브로커가 `memory.add`(부수효과) **이전**에 `interrupt(payload)`로 그래프를 멈추고, 승인돼야만 저장한다
  (기존 HIL 파이프라인 재사용 — 스펙 101 §3.5, 새 배선 0).
- 승인 payload는 **저장될 사실을 그대로 노출**한다(MCP처럼 마스킹 X — 사람이 승인하려면 무엇이
  저장되는지 봐야 한다). `permission="memory.write"`, `action="memory.write"`, `args={"text": <fact>}`,
  `summary="장기 기억에 저장: <preview> — 승인 필요"`.
- **저장은 승인한 그대로**(`infer=False`, 원문 verbatim — 스펙 029 경로). LLM이 승인과 저장 사이에서
  재해석하지 않는다: 사람이 승인한 문구 = 저장되는 문구.

## 읽기와 쓰기는 별도 권한 (최소권한)
- **별도 kind `memwrite`** → RBAC `capability:memwrite`(읽기 `capability:memory`와 분리). "내 기억을
  읽게는 해도 쓰게는 안 함"이 가능. cap_id = `memwrite:user`. 기본 정책은 admin('*','*')만 → member는
  `capability:memwrite` 거부(deny-by-default, 쓰기는 고권한).

## 승인 주체 (누가 승인하나) — 소유자 self-승인 기본(사용자 결정 2026-07-02)
- 자기 기억 쓰기는 **소유자 본인 승인이 자연스럽다**(admin이 남의 개인 기억 쓰기를 승인하는 건 부적절).
  그래서 permission `memory.write`에 **소유자 self-승인을 기본으로 연다**: `_DEFAULT_POLICIES`에
  `("member", "memory.write", "self_approve")` 추가. `users.on_after_register`가 모든 일반 유저에
  `member` role을 부여하므로(확인됨) 이 정책이 유효 — 에이전트가 "기억할까요?"로 멈추면 **소유자 본인이**
  자기 ApprovalsView에서 승인한다(066 self-approve 경로 재사용, 새 배선 0).
- **여전히 사람 게이트**: self-승인도 사람이 저장 전 확인하는 것(learning 031의 구조적 방어). LLM이
  자동 저장하지 않는다 — 반드시 소유자가 명시 승인. admin은 066 admin 분기로 언제나 승인 가능(무회귀).
- **안전성**: 자기 스코프(user_id) 쓰기라 self-승인이 교차유저 누출을 열지 않는다(051은 agent_id 축 문제).
  민감 perm(`data.delete`)의 admin-필수와 달리, 자기 기억 쓰기는 소유자 self-승인이 옳은 민감도 등급.

## 구현

### cap_id 네임스페이스
- `CAP_KIND_MEMORY_WRITE = "memwrite"`, 접두 `memwrite:`. `_kind_of`에 분기 추가(agent/mcp/rag/memory 무회귀).
- `_parse_memwrite(item)` — `memwrite:` 스트립(첫 출하 `"user"`만 유효). `_parse_mem`과 대칭.

### MemoryWriteProvider (broker.py, MemoryProvider 거울 + 승인)
생성자 `MemoryWriteProvider(session_factory, user_id)` — user_id는 build_broker가 principal서 주입(104와 공유).
6메서드:
- `candidates(allow)`: `memwrite:user`가 allow에 있고 **user_id 있을 때만** 정적 cap 1개(머신→[]).
- `load(cap_id)`: 리소스 `user` 아니거나 user_id 없으면 None(존재 비노출).
- `describe(row)`: input_schema `{text: required}`(저장할 사실). **user_id 필드 없음**(주체 고정).
- `invoke(row, args)`: text 빈값이면 error·**무저장**. else `memory.add({"user_id": self._user_id},
  [{"role":"user","content":text}], mem_cfg, infer=False)`. 결과=저장 확인 텍스트, trust="untrusted".
  **args의 어떤 필드도 user_id로 안 씀**(anti-leak).
- `node_label(row)`: `broker_invoke:memwrite:user`.
- `approval_for(cap_id, args)`: **항상 payload**(위 형식, text 미마스킹). 쓰기=부수효과.

### 배선
- `PolicyScopedBroker._providers`에 `MemoryWriteProvider(session_factory, user_id)` 추가(read provider 옆).
- build_broker·_build_resume_broker는 이미 user_id 주입(104) — 무변경(새 provider가 같은 user_id 받음).

## RBAC / 소유권 경계 체크리스트 (발동 — 유저별 데이터 쓰기)

1. **입구 열거(닫힌 집합)** — 브로커 memwrite 입구 = **{discover, describe, invoke}**. invoke만 부수효과
   (쓰기)이고 승인 게이트 뒤. update/delete/resume/lazy-create 없음(add만). 기존 memory_routes CRUD(053)는 밖.
2. **입구별 소유권** — 쓰기(invoke): owner user_id를 add 스코프에 묶어 자기 기억에만 쓴다(§2c 생성 시
   1회 소유자 스탬프 = 여기선 scope의 user_id). principal 도출값, **cap_id·args 불가**. 승인 게이트가
   부수효과 이전에 사람 확인(§2b 쓰기 소유자 덮어쓰기 금지 — 남의 스코프 못 씀).
3. **단일 헬퍼** — user_id 도출 build_broker 한 곳, 쓰기 스코프 구성 invoke 한 곳(drift 0, read와 대칭).
4. **존재 비노출** — allow 밖 → not-found. 머신·비-user 리소스 → candidates []·load None.
5. **검증 사다리 3런(비겹침)**:
   - ① **단위**: `_kind_of`/`_parse_memwrite` 네임스페이스(무회귀), `_permitted` memwrite, **approval_for가
     항상 non-None**(읽기와 정반대 — 부수효과), describe 스키마(text·user_id 필드 부재), candidates 게이트,
     머신→[], `_by_kind`에 memwrite, invoke가 **승인 없이는 호출 안 됨**(브로커 흐름)·args user_id 무시·
     빈 text 무저장, permission `memory.write`가 **소유자 self-승인 가능**(member 기본 정책)·`data.delete`는
     여전히 불가(민감도 구분 무회귀).
   - ② **실 인프라 통합(seed+restart)**: 실 mem0. **승인 왕복** — (a) 브로커 invoke가 write 이전 interrupt
     (부수효과 0 = 저장 안 됨), (b) **reject → 무저장**(mem0에 안 생김), (c) **approve → 정확히 1회 저장**
     (그 fact가 자기 user_id 스코프에 생기고 **타 유저 스코프엔 안 생김**), (d) 저장된 사실을 104 읽기로
     회상 가능(쓰기→읽기 왕복). RBAC deny(capability:memwrite 없음)→discover [].
   - ③ **적대 타자(codex)**: 여집합 — 승인 우회(interrupt 없이 저장?)·args로 타 user_id/agent_id 밀반입·
     빈/거대 text·승인-저장 사이 재해석·멱등(재개 시 중복 저장?).
6. **자가-잠금 핀** — 소유자는 자기 기억에 정상 저장 가능(승인 후). 조임이 정당한 self-write를 막지 않음.

## 완료 조건 (측정 가능)

- verify_105_broker_memwrite: 단위 + 실 mem0 통합, **승인 왕복(reject=무저장 / approve=1회 저장·자기
  스코프)**·쓰기→읽기 왕복·교차유저 무저장을 수치로 실증. all pass.
- 무회귀: verify_100/101/102/103/104 + 084 통과.
- codex 여집합 3판정 완료.
- 회고 086 + learning 105 + INDEX 3종 + 백로그 갱신 + per-spec 커밋(푸시/머지 없음).

## 비목표 (OUT — 다음/경계)

- **다중 interrupt 멱등 재개** — 한 delegate 노드가 memwrite + 다른 승인 cap을 순차 위임하다 재개하면
  이미 승인된 쓰기가 중복 저장될 수 있다(스펙 101·102가 이미 OUT으로 문서화한 **기존 경계** —
  interrupt-before-sideeffect는 단일 cap엔 exactly-once, 다중은 별도 난제). 첫 출하 안전 경로 = **한 번에
  memwrite 하나**(또는 memwrite를 마지막에). 이 스펙이 새로 만든 결함 아님 — 물려받은 경계로 명시.
- **infer=True 통합 저장** — mem0가 사실을 추출·통합하는 모드. 승인-저장 일치(verbatim)를 위해 이번은
  infer=False. 통합 저장은 별도.
- **agent_id·run_id 쓰기** — agent_id는 051이 금한 교차유저 누출 축(어드민 저작 전용 유지), run_id는 휘발성.
- **memory 수정(update)·삭제(delete)** 능력 — add만. 수정/삭제는 대상 mem_id 소유권 검증(053 `_assert_user_owns`)
  이 별도로 필요.
- **admin의 memory-write 승인 열람/결정** — self-승인이 기본 경로지만 admin(및 머신)은 066 admin 분기로
  임의 유저의 memory-write 승인을 `/approvals`에서 보고 approve/reject할 수 있다(적대 리뷰 105 P2). **새
  노출 아님**: admin은 이미 053(`memory:manage`)로 임의 유저 기억을 읽고 큐레이션할 권한이 있어, 승인
  뷰에서 사실을 보는 것이 admin 권한을 넓히지 않는다. 안전 불변식(저장 스코프는 승인자 무관 항상 요청자
  user_id — 교차유저 쓰기 0)은 유지되고 검증됨(G-테스트). **후속(원하면):** memory.write 승인을 owner-only
  resolve로 분기하거나 비-owner 승인 뷰에서 args.text를 마스킹. 이 스펙은 기존 admin 감독 모델을 존중해
  경계로 명시.

## codex 적대 리뷰(3판정, P0/P1 없음)

- **[P2 실결함]** 승인·저장 사실 길이 무제한 — 거대 text(`"가"*50000`)가 승인 DB(JSONB)·응답·저장 기억을
  무제한 점유(103/104 P2 동형 교차입구 갭). → `_memwrite_text` 공유 헬퍼로 4000자 상한(MemorySearchIn 질의
  상한과 동일 경계). approval_for·invoke가 **같은 헬퍼**로 자르므로 "승인한 것 == 저장되는 것"(길이도 일치).
- **[P2 미문서 경계]** admin의 타인 memory-write 승인 열람/결정 — 위 비목표에 명시(admin은 053으로 이미
  임의 유저 기억 접근 → 새 노출 아님, 안전 불변식은 승인자 무관 유지). 명시화로 처리(고침도 기각도 아님).
- **오탐 기각**: args의 user_id/agent_id/run_id scope 주입(invoke는 `{"user_id": self._user_id}`만),
  approval_for가 None 되는 경로 없음, 머신 차단 — 전부 공격 실패.
