# 020 — mem0를 설계 의도대로: user/session 다층 스코프 + 카탈로그 재정렬

상태: **실행 완료 — 단위 검증 통과 + 타자 검증(P1·P2 0건). 라이브 통합 테스트는 사용자 브랜치 잔여(회고 010 선례)**
날짜: 2026-06-24
브랜치: `feat/agent-service` — **main 머지·push 금지**(사용자가 직접 브랜치 테스트)
지배 스펙: [007-real-agent-service](007-real-agent-service.md)(Phase 2 — 메모리), [018-memory-user-scoping](018-memory-user-scoping.md), [019-mem0-pgvector-shared-backend](019-mem0-pgvector-shared-backend.md)
연관 코드: `packages/api/src/api/memory.py`, `chat.py`, `blocks.py`, `seed.py`, `models.py`, `serializers.py`; `admin/src/playground/Inspector.tsx`, `admin/src/admin/views/{AgentsView,BlocksView}.tsx`, `admin/src/admin/mockData.ts`, `admin/src/playground/agentData.ts`

---

## 배경 — "메모리 종류 4개"는 mem0를 쓰는 방식이 아니다 (웹·소스 대조로 확정)

조사(설치 소스 2.0.7 + 공식 문서/이슈/사례)로 다음을 확정했다:

1. **mem0의 이점은 "memory_type 스위치 N종 구현"이 아니다.** 공식 [Memory Types 문서](https://docs.mem0.ai/core-concepts/memory-types)는 semantic/episodic/procedural/factual을 **개념적(심리학) 분류**로 설명하고, 실제 API는 **scope 레이어**(`user_id`/`agent_id`/`run_id`)로 동작한다. mem0가 가치를 내는 메커니즘은 셋이다:
   - **추출·정리 파이프라인**(`infer=True`, 기본) — 대화에서 LLM이 사실 추출·중복제거.
   - **다층 스코프** — id 축으로 태깅, 질의 시 해당 축으로 필터.
   - **자동 엔티티-그래프** — 신버전 mem0는 외부 graph_store(Neo4j 등)를 제거하고 add 파이프라인에서 엔티티를 자동 추출해 `{collection}_entities`에 적재(외부 인프라 0). 우리 2.0.7은 이미 add Phase 7 엔티티 링킹 + search 부스팅을 갖는다(소스 확인).
2. **episodic은 구현 대상이 아니다** — 패키지 전체에서 enum 정의 1곳에만 등장, `add`에 넘기면 `Mem0ValidationError`로 거부(`memory/main.py:713-718`). 스코프(run_id)+추출로 실현되는 개념 범주일 뿐.
3. **procedural은 mem0에 경로가 있으나(`_create_procedural_memory`) "실행 이력 1회 LLM 요약"** 이다 — 카탈로그가 약속한 "규칙의 점진적 누적"과 다르며 `agent_id` 필수.

→ 즉 우리 UI의 "단기/의미론적/일화적/절차적 4종 토글"은 **mem0의 가치 전달 방식과 범주가 어긋난** 시드 카탈로그(`007:46`에서 그렇게 명명)다. 그리고 우리 코드는 **세 스코프 축을 `user_id` 하나에 합쳐**(`chat.py:265` `user:X`/`session:X` 접두사) mem0 본연의 다층 회상을 못 살리고 있다.

## 루트 스펙과의 일치 — 이미 요구된 것을 이행하는 것

루트 스펙(`docs/spec/CLAUDE.md`)은 메모리를 이렇게 정의한다:

> "메모리 (**작업 기억과 같은 에이전트 전용 메모리**, **유저에 대한 메모리** 등 Mem0에서 제공하는 메모리 기능)"

이는 mem0의 스코프 축과 1:1로 맞는다. 본 작업은 새 요구가 아니라 **루트 스펙이 명시한 두 메모리(유저/에이전트)를 비로소 이행**하는 것이다:

| 루트 스펙 문구 | mem0 축 | 의미 | 현재 |
|---|---|---|---|
| 유저에 대한 메모리 | `user_id` | 세션·에이전트를 가로지르는 유저 사실 | ⚠️ 쓰지만 session과 뭉뚱그림 |
| 작업 기억 = 에이전트 전용 메모리 | `agent_id` | 그 에이전트가 학습한 일반 지식(유저 불문) | ❌ 미사용 |
| (세션 단기) | `run_id` | 현재 세션 한정 휘발성 사실 | ❌ 미사용(`user_id`에 우겨넣음) |

## 결정 (사용자 승인)

- **이번 스펙은 user/session 두 축만 도입** — `user_id`(유저 사실, 세션 가로지름) + `run_id`(세션 단기)를 직교 레이어로 분리. 단일축 접두사 해킹(`user:X`/`session:X`) 제거.
- **`agent_id`(에이전트 전용 메모리)는 후속으로 분리** — "에이전트 메모리 = 유저와 무관한 에이전트 자신의 사실"로 정의가 깨끗해져 누수는 구조적으로 사라졌으나, **자동 공급원이 없어(유저 대화에서 안전 추출 불가) 의도적 쓰기 채널이 필요**하다. 안전한 쓰기 채널(관리자 저작 등)을 확정하면 별도 스펙으로 추가. **이번엔 UI에 노출하지 않는다**(채울 수 없는 "죽은 서랍"을 만들지 않기 위해).
- **UI 카탈로그를 스코프 모델로 재정렬** — 심리학 4종 토글을 mem0 실제 모델(유저/세션 스코프 + 메모리 on/off)로 정직하게 재표현, 백엔드와 일치. 죽은 토글(일화적·절차적·에이전트) 제거.

---

## mem0 스코프 메커니즘 (소스 확정 — 설계의 토대)

`_build_filters_and_metadata`(`memory/main.py:272-355`)에서 확인:

- **add 시**: 제공한 모든 id가 `base_metadata_template`에 태깅된다(여러 축 동시 가능).
- **search 시**: 제공한 모든 id가 `effective_query_filters` **한 dict에 들어가 AND로 질의**된다.
- **함의(핵심)**: 풍부 태깅된 기억(`{user_id:U, agent_id:A, run_id:S}`)은 **부분집합 필터로도 회상**된다 — `filter={user_id:U}`는 user_id==U인 레코드를 (다른 키 무관) 모두 매칭. 필터 키가 늘수록 **좁아진다**(교집합). 합집합 회상은 한 질의로 불가 → **레이어별 검색을 병합**해야 한다.

### ⚠️ 누수 위험 (반드시 설계에 반영)

풍부 태깅 + 광역 축 회상은 **사생활 누수**를 만든다:
- 유저 A의 턴을 `add(user_id=A, agent_id=AG)`로 저장하면, 다른 유저 B의 세션에서 `search(agent_id=AG)`가 **A의 사적 사실을 회상**한다.
- mem0의 추출기는 사실을 "유저 것/에이전트 것"으로 **분류해 주지 않는다** — 어느 축에 쓸지는 전적으로 호출자(우리) 책임.

→ **정책 원칙: 쓰기 축은 "그 사실의 소유자"로만 한정한다.** 유저 턴은 유저(+세션)에만, 에이전트 일반지식은 유저 식별자 없이 에이전트에만.

---

## 설계 (확정)

### 축별 의미·쓰기 정책 (이번 스펙)

| 축 | 저장 내용 | 쓰기 시점 | 누수 안전 |
|---|---|---|---|
| `user_id=U` | 유저 사실(취향·맥락) — 세션 가로지름 | userId 있는 매 턴 (자동) | U에만 태깅, agent_id 미부착 → 다른 유저로 안 샘 |
| `run_id=S` | 세션 한정 사실 | 매 턴 (자동) | run_id는 세션마다 고유 → 다른 세션으로 안 샘 |
| ~~`agent_id`~~ | (에이전트 전용 — **후속 스펙**) | — | 정의상 유저 사실 미혼입 → 안전하나 쓰기 채널 미정 |

**핵심**: 유저 턴의 자동 쓰기는 **user+session 두 축만**. `agent_id`는 시그니처에 자리만 예약(아래 A)하고 이번엔 도출·노출하지 않는다.

### 회상(읽기) 구성 — 레이어별 검색 병합

필터가 AND이라 합집합은 한 질의로 불가 → 축별 검색 후 병합:
- **userId 있음**: `search(filters={user_id:U})` ∪ `search(filters={run_id:S})` → id 기준 dedup, score 내림차순, top-k(`limit`).
- **userId 없음**: `search(filters={run_id:S})` — 세션 단기만.
- 각 검색은 단일 축 필터 → 누수 없음. 병합은 `memory.py` 내부에서. 트레이스 hit에 출처 축 표기.

### 쓰기(저장) — userId 유무

- **있음**: `add(messages, user_id=U, run_id=S)` (한 번; 두 축 동시 태깅 → user/session 양쪽 회상에 잡힘).
- **없음**: `add(messages, run_id=S)`.

---

## 변경 계획

### A. `memory.py` — 단일 scope_id API를 다축으로 교체
- `search(scope_id, ...)` / `add(scope_id, ...)`의 `scope_id: str` 시그니처를 **스코프 dict**(`{"user_id","agent_id","run_id"}`, None 허용)로 교체. **`agent_id`는 시그니처에 자리만 예약**(이번엔 항상 None) — 후속 스펙에서 채울 때 API 변경 없이 확장 가능.
- `search`: None이 아닌 축마다 `mem.search(filters={axis: val})` 호출 → 결과 병합(id dedup, score 내림차순, `limit`). 트레이스용 `[{type, text, score, scope}]`에 어느 축에서 왔는지 표기.
- `add`: 제공된 축으로 `mem.add(messages, user_id=?, run_id=?)` (None 축은 생략).
- `memory_enabled()`: 현재 `"장기·의미론적"` 정확 문자열 의존(`memory.py:69`). 재정렬된 카탈로그 키로 게이팅 변경(아래 C와 동기). graceful 무력화·`_cfg_key` 캐시는 유지.

### B. `chat.py` — 세 축 도출, 접두사 해킹 제거
- `mem_scope = f"user:..."/"session:..."`(`chat.py:265`) 제거.
- 도출: `user_id = body.userId or None`; `run_id = ctx["session_id"]`. `agent_id`는 이번엔 도출하지 않음(후속).
- `memory.search`/`memory.add`에 스코프 dict 전달.
- 트레이스 `memoryScope`(`chat.py:322`)를 **다축 표현**으로 교체(예: `{user_id, run_id}` + 회상 hit별 출처 축). Inspector 렌더와 동기(C).

### C. 카탈로그·UI 재정렬 (스코프 모델로)
- `seed.py:34-39` `MEMORY_TYPES` 4종(단기/의미론적/일화적/절차적)을 **스코프 모델**로 재정의. 제안 표현:
  - **"단기(세션) — 인-컨텍스트 윈도우"**: mem0 아님, `historyDepth` 윈도우. 실재하므로 유지하되 "mem0 아님" 명확화.
  - **"장기 메모리 (mem0)"**: 기존 "의미론적" 대체. 켜면 사실을 기억; **스코프는 요청 userId 유무로 자동 결정**(있음=유저 장기, 없음=세션 단기). 별도 토글 아님.
  - **일화적·절차적 제거**(죽은 토글). 에이전트 메모리도 노출 안 함(후속).
  - `models.py` `MemoryType`(name/key/scope/body) 스키마는 유지, 시드 내용만 교체.
- `blocks.py` `/memory-types`·`/blocks` 직렬화(`blocks.py:355-385`)는 카탈로그 내용만 바뀌므로 구조 변경 최소.
- `AGENTS` 시드(`seed.py:74+`)의 `memories` 값(`["단기(세션)","장기·의미론적"]` 등)을 새 키로 마이그레이션.
- 어드민: `Inspector.tsx:265-275`(메모리 타입 목록 + `memoryScope` 태그 "유저 장기/세션 단기")를 다축 표현으로, `agentData.ts`(`memoryScope?: string`) 타입 확장, `mockData.ts`의 4종 참조 갱신, `AgentsView`/`BlocksView`의 메모리 선택 UI 갱신.
- **DB 데이터 마이그레이션**: 기존 agents의 `config.memories` 문자열 값이 새 키와 다르면 `memory_enabled`가 깨진다 → 시드 재적용 또는 일회성 변환 명시.

### D. ~~agent 축 배선~~ → 후속 스펙
이번 스펙 제외. `memory.py` 시그니처에 `agent_id` 자리만 예약(A). 안전한 쓰기 채널(관리자 저작 등) 확정 후 별도 스펙.

---

## 검증 (완료 조건)

- [ ] **AND 필터 실증**: `{user_id:U, run_id:S}`로 add → `filter={user_id:U}`와 `{run_id:S}` 각각으로 회상됨, `{user_id:U2}`로는 안 됨(라이브 mem0+Postgres).
- [ ] **누수 없음(핵심)**: 유저 A 턴 저장 후, 유저 B 세션의 회상에 A의 사실이 **안 나옴**. 다른 run_id 세션의 단기 사실도 안 샘(세션 격리).
- [ ] **다층 합집합 회상**: userId 있는 세션에서 유저 사실 + 세션 사실이 한 응답에 병합·dedup·정렬되어 회상.
- [ ] **유저 장기 지속**: 새 세션(run_id 다름)에서도 같은 userId 유저 사실이 회상(cross-session).
- [ ] **카탈로그 일치**: UI가 보여주는 메모리 모델 = 백엔드 실제 동작. 죽은 토글(일화적·절차적·에이전트) 없음.
- [ ] **graceful 유지**: 임베딩 서버 다운/메모리 미사용 시 채팅 정상(기존 무력화 회귀 없음).
- [ ] **마이그레이션**: 기존 시드/agents의 memories 값이 새 게이팅에서 정상 동작.
- [ ] **타자 검증**: 서브에이전트/codex로 (1) 세션↔유저 누수 없음, (2) 다축 병합·dedup, (3) chat.py 축 도출·카탈로그 게이팅 비판 리뷰. 자가검증 지양([[009-memory-user-scoping]]·[[010-mem0-pgvector-migration]]에서 타자 검증이 P1을 잡은 전례).

---

## 범위 밖 (이번 스펙 제외)

- **`agent_id` 에이전트 전용 메모리** — 정의는 깨끗(유저 사실 미혼입)하나 안전한 쓰기 채널(관리자 저작 등)이 필요. 채널 확정 후 별도 스펙. 이번엔 `memory.py` 시그니처 자리 예약만.
- **procedural 메모리 실배선**(`_create_procedural_memory`) — agent 축 쓰기와 함께 후속.
- **episodic 자체 구현** — mem0 밖(원문 로그+요약 잡). 별도.
- 히스토리 DB 공유, A2A, LangGraph checkpointer.

## 비고

- mem0 필터 AND·부분집합 회상은 `memory/main.py:272-355` 실측 기준. 벡터 스토어(pgvector) 필터 처리도 동일 가정 — 검증 항목 1에서 실증.
- main 머지·push 금지. 검증 후 사용자가 직접 브랜치 테스트.
- 기존 단일축 데이터(`user:X`/`session:X` 접두사로 저장된 mem0_memories)는 새 축 스킴과 키가 달라 회상 단절될 수 있음(018/019의 재스코핑과 동형 — 회귀 아님). 필요 시 TRUNCATE 또는 마이그레이션 별도.
