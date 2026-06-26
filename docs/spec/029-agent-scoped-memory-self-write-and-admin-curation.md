# 029 — 에이전트 전용 메모리(agent_id): 에이전트 자가 기록 + 관리자 큐레이션

상태: **승인 — 실행 착수**(Planning 완료)
날짜: 2026-06-26
브랜치: `feat/agent-service` — **main 머지 금지**(사용자 직접 브랜치 테스트 예정)
지배 스펙: [020 다층 스코프](./020-mem0-multi-scope-and-catalog-realign.md)(이 스펙이 명시적으로
미룬 후속분), 루트 스펙 `docs/spec/CLAUDE.md`("메모리 = 작업 기억 같은 에이전트 전용 메모리")
참고: `.dev/learning/021-mem0-value-is-scope-not-types`, `.dev/learning/019-mem0-memory-scoping`

## 배경 / 문제

020이 mem0 스코프를 `user_id`(유저 사실)·`run_id`(세션 단기)로 펼쳤으나 **`agent_id`(에이전트
전용 사실)는 의도적으로 보류**했다. 보류 사유(020 원문): *"자동 공급원이 없어(유저 대화에서 안전
추출 불가) 의도적 쓰기 채널이 필요. 안전한 쓰기 채널(관리자 저작 등)을 확정하면 별도 스펙으로
추가. 채울 수 없는 '죽은 서랍'은 UI에 안 만든다."*

현 상태(소스 확인):
- `memory.py`는 **이미 agent_id를 구조적으로 지원**(`_SCOPE_AXES`에 포함, `add`/`search`가
  임의 축 처리). 빠진 건 순전히 **공급(쓰기)·배선(읽기)·노출(UI)**.
- `chat.py:310` → `mem_scope = {"user_id":…, "run_id":…}` — agent_id를 끼우지 않음.
- 즉 020의 레일 위에 **agent_id 한 축만 실으면** 루트 스펙의 "에이전트 전용 메모리"가 채워진다.

## 결정 — 쓰기 채널을 두 겹으로 (사용자 결정)

> 사용자: *"에이전트가 회상하여 스스로 메모리에 기록할 수 있도록 해주고, 관리자가 수정할 수
> 있도록 해 주는 것 어때?"*

1. **에이전트 자가 기록** — 에이전트가 대화 중 "이건 내 일반 지식"이라 판단한 사실을
   **의도적 도구 호출**로 agent_id에 기록한다.
2. **관리자 큐레이션** — 관리자가 Admin UI에서 그 기억을 **조회·수정·삭제**한다(교정막).

## 누출 안전성 (020 원칙 "쓰기 축 = 사실의 소유자" 준수)

020이 막은 건 **유저 턴 자동추출**(`infer=True` over 유저 대화 → user A의 사적 사실이 agent_id로
새어 user B에게 회상)이다. 본 설계는 그 위험 경로를 피하면서 안전 채널을 연다:

- **의도적, 자동 아님.** agent_id 쓰기는 **에이전트가 명시적으로 도구를 호출할 때만** 발생한다.
  매 턴 대화를 추출해 agent_id로 태깅하지 **않는다**. (이게 020이 요구한 "의도적 쓰기 채널".)
- **순수 agent 스코프 쓰기.** 자가기록은 **agent_id만** 태깅한다(user_id·run_id 안 붙임).
  → 어떤 경우에도 **특정 유저의 user_id 메모리를 오염시키지 않는다**. 최악의 경우라도 같은
  에이전트를 쓰는 다른 유저에게 보일 뿐(= 에이전트 지식의 본래 성질).
- **`infer=False`로 원문 저장.** 에이전트가 고른 한 줄 사실을 LLM이 재추출해 모양을 바꾸지 않게
  그대로 저장 → 예측 가능·관리자 검수 용이.
- **도구 프롬프트 규율.** 도구 설명에 "재사용 가능한 일반 지식(역할·도메인·절차)만 저장, 지금
  대화 중인 특정 유저에 대한 정보는 절대 저장 금지"를 명시.
- **관리자 교정막.** 에이전트는 *제안*, 관리자가 *처분*(edit/delete) — 사람이 누출을 잡는다.
- (후속 하드닝, 이번 범위 밖) 더 강한 보장이 필요하면 **승인 게이트**(에이전트 쓰기 = pending →
  관리자 승인 후 active)를 추가할 수 있다. 이번엔 "쓰기 즉시 활성 + 관리자 사후 교정" 모델.

### 잔여 위험 (라이브 검증으로 노출, 사용자 수용 — 2026-06-26)

라이브 테스트가 한 겹을 더 드러냈다: **유저가 "이거 기억해줘"라고 하면 LLM(qwen)이
`save_agent_knowledge`를 스스로 호출**해 그 유저의 PII를 agent_id에 쓸 수 있다. agent_id 기억은
모든 유저에 회상되므로, 도구 프롬프트의 "유저 정보 저장 금지" 규율만으로는 막지 못한다(사용자
지시가 프롬프트 규율을 이긴다). **두 경로를 분리해서 봐야 한다:**

- **자동 턴-add 경로** = 불변식. agent_id를 절대 안 붙인다 → 이 경로 누출 **0**(코드로 보장,
  테스트로 검증). 020이 막으려던 자동추출 누출은 닫혀 있다.
- **의도적 자가기록 채널** = 사용자 수용 위험. 에이전트가 도구를 명시 호출할 때만 발생하며,
  유저 PII가 섞일 수 있다. **사용자 결정(2026-06-26): "현행 유지 — 즉시 활성, 사후 삭제."**
  → 쓰기를 게이트로 막지 않고, 관리자가 사후에 PII를 솎아낸다(쓰기/교정 분리의 직접 귀결).
  관리자가 치우기 전까지 타유저 노출 창이 존재함을 **명시적으로 받아들인다**. 더 강한 보장이
  필요해지면 위의 "제안 풀" 또는 "승인 게이트"를 후속 스펙으로 올린다.

## 변경 범위

### A. 회상 배선 — `packages/api/src/api/chat.py`
- `mem_scope`에 agent_id 추가: `{"user_id":…, "run_id":…, "agent_id": ctx["ext_agent_id"]}`.
  `memory.search`는 이미 축별 검색 후 병합 → 에이전트가 **세션·유저를 가로질러 자기 지식 회상**.
- 단, **턴 자동 `memory.add`는 현행대로 user_id+run_id만**(agent_id 미포함) — 자동추출 누출 차단 유지.
- 주석의 "agent_id는 후속 스펙까지 미노출"을 본 스펙 반영으로 갱신.

### B. 자가기록 도구 — `runtime.py` + `chat.py`
- 빌트인 `StructuredTool` **`save_agent_knowledge(fact: str)`**를 mem0 켜진 에이전트의 toolset에 주입.
  호출 시 `memory.add({"agent_id": ext_agent_id}, [{"role":"user","content":fact}], mem_cfg, infer=False)`.
- 호출은 `calls_sink`에 기록 → Playground Inspector에서 가시화(트레이스 일관).
- mem0 비활성/실패 시 graceful(도구 미주입 또는 no-op).

### C. mem0 헬퍼 — `packages/api/src/api/memory.py`
- `add(scope, messages, mem_cfg, infer=True)` — `infer` 파라미터 추가(기본 True 유지, 자가기록만 False).
- `list_memories(scope, mem_cfg)` — `mem.get_all(filters={axis:val})` 래핑 → `[{id, text}]`.
- `update_memory(mem_id, text, mem_cfg)` — `mem.update`.
- `delete_memory(mem_id, mem_cfg)` — `mem.delete`. (모두 graceful 무력화.)

### D. 관리자 CRUD API — `packages/api/src/api/agents.py`
- `GET /agents/{id}/memory` → agent_id 기억 목록.
- `POST /agents/{id}/memory` `{text}` → 관리자 저작 add(agent_id-only, infer=False).
- `PATCH /agents/{id}/memory/{memId}` `{text}` → 수정.
- `DELETE /agents/{id}/memory/{memId}` → 삭제.

### E. Admin UI — `admin/src/admin/views/AgentsView.tsx`
- mem0 켜진 블록(현 ~201/1131줄 조건부)에 **"에이전트 지식" 패널**: 목록 + 인라인 수정 + 삭제 +
  수동 추가. `admin/src/api.ts`에 호출 추가.

## 실행 단계(병렬·순서)

1. **백엔드 핵심**(A·B·C 동시 가능) → 라운드트립 통합 테스트.
2. **관리자 API**(D) → API 레벨 테스트.
3. **Admin UI**(E) → 브라우저 검증.

## 검증 (측정 가능 · 자가검증 지양)

1. **라운드트립 통합**(라이브 qwen + 공유 pgvector):
   - chat 호출 → 에이전트가 `save_agent_knowledge` 호출 → `mem0_memories`에 **agent_id만** 태깅된
     행 생성(assert: user_id·run_id 빈값).
   - **다른 세션·다른 userId**로 재호출 → 그 사실이 `mem_hits`에 `scope="agent_id"`로 회상.
   - **누출 검증(자동 경로 불변식)**: **자동 턴-add**로 저장된 user 사실이 agent_id 태깅을 갖지
     않음 → agent_id 검색에 **0건**. (의도적 자가기록 채널의 PII는 잔여 위험으로 수용 — 위 절 참조.)
2. **관리자 CRUD**: list/add/edit/delete 라운드트립(API 테스트).
3. **브라우저**: Admin 에이전트 편집 → "에이전트 지식" 패널 표시·add/edit/delete 동작(Playwright,
   `tests/browser/`). UI 수정은 내가 먼저 브라우저로 확인.
4. **서브에이전트/codex 비판 리뷰**: agent_id-only 쓰기(누출 차단), `infer=False`, graceful
   무력화, 자동 add가 agent_id를 포함하지 않는지(회귀).

## 완료 조건

- [x] chat.py 회상 스코프에 agent_id 배선(자동 add는 agent_id 미포함 유지)
- [x] `save_agent_knowledge` 도구(agent_id-only, `infer=False`) — Inspector 트레이스 가시화
- [x] memory.py `list_memories`/`update_memory`/`delete_memory` + `add(infer=)` 헬퍼
- [x] 관리자 CRUD API 4개 엔드포인트 (+ `_assert_owns` 소유권 가드 — 비판리뷰 HIGH 대응)
- [x] Admin UI "에이전트 지식" 패널(list/add/edit/delete) — 브라우저 렌더 확인
- [x] 누출 검증(자동 경로): **자동 턴-add** user 사실이 agent_id 검색에 **0건**(의도 채널 PII는 수용)
- [x] 라운드트립 통합 테스트 PASS(저장→타세션·타유저 회상; CRUD 프록시 경로 라이브)
- [x] 브라우저 검증 + 서브에이전트 비판 리뷰 PASS(HIGH 1건 수정, 나머지 med/low/nit)
- [x] **main 머지 금지** (커밋만, 푸시/머지 안 함)

> **검증 요약(2026-06-26):** 단위 29/29 PASS, tsc 0. 라이브: CRUD 라운드트립(POST201/GET/PATCH200/DELETE204),
> 소유권 가드(타 에이전트 경로 변조 → 404, 원본 무사), 브라우저 패널 렌더·게이트(ui+mem0 한정).
> 비판리뷰 HIGH(교차-에이전트 id 변조) 수정. 잔여 MED(mem_cfg 해석 중복, add가 id 미반환)는 후속.

## 결정된 선택지 (사용자 승인 2026-06-26)

- **승인 모델 = 즉시 활성 + 관리자 사후 교정.** 사용자: *"관리자가 매번 승인하기가 어려워.
  에이전트가 기억을 쓰는 것과 교정을 분리해서 보자."* → **쓰기(에이전트)와 교정(관리자)을 분리** —
  에이전트 쓰기는 게이트 없이 즉시 활성, 관리자는 별도 화면에서 사후 조회·수정·삭제. 승인 게이트는
  채택하지 않는다(필요 시 후속 하드닝).
- **자동 add 정책 = agent_id 안 붙임 고정**(누출 안전 유지).
- **범위 = 한 스펙(A~E 전부).**
- **자가기록 PII 누출 = 현행 유지(즉시 활성, 사후 삭제).** 라이브 검증이 "유저가 기억해줘 하면
  에이전트가 PII를 agent_id에 쓸 수 있다"를 드러냈고, 사용자: *"현행 유지 (즉시 활성, 사후 삭제)."*
  → 도구를 막지 않고 관리자 큐레이션으로 흡수. 타유저 노출 창은 수용. (상세: "잔여 위험" 절.)
