# 084 — 메모리 조회 시험 도구 (관리 콘솔 "조회 시험" 드로어)

## 배경 (실측)

사용자: **"메모리 조회 기능 필요. 플레이그라운드에서 인스펙터 드로워를 보면 메모리에서 검색했다고
하는데 실제 테스트 불가능."**

플레이그라운드 인스펙터는 회상 *행위*(`memoryQuery` 에코·`memoryScope`)를 보여준다(스펙 079). 그러나
"이 쿼리로 무엇이 회상되는가"를 *직접 시험*할 수단이 없다 — 실제 대화를 돌려야만 회상이 일어난다. RAG는
이미 072에서 같은 공백을 "검색 시험" 드로어로 닫았다(공유 코어 + `/search` 엔드포인트 + 관리 UI).

**핵심 비대칭(072 대비 더 쉬움):** RAG는 retrieval 본체를 `search_collections`로 *추출*해야 했지만, 메모리는
공유 코어 `memory.search(scope, query, mem_cfg, limit) -> [{type,text,score,scope}]`가 *이미* 존재하고
챗(`chat.py:528`)이 그대로 쓴다. 따라서 엔드포인트가 **직접 호출**하면 끝 — drift 위험 없음.

**메모리는 두 스코프** (`memory/backend.py:22` `SCOPE_AXES`): `agent_id`(에이전트 전용 기억)·`user_id`(유저
사실). 관리 콘솔 MemoryView도 두 탭(에이전트/유저)이라, 조회 시험도 **두 갈래**로 미러한다.

## 목표 (완료 조건 — 측정 가능)

1. **백엔드 시험 엔드포인트 2개**(읽기 전용, 공유 코어 `memory.search` 직접 호출):
   - `POST /agents/{agent_id}/memory/search` — `{"agent_id": agent.agent_id}` 스코프
   - `POST /memory/user/{user_id}/search` — `{"user_id": user_id}` 스코프
2. **입력 신뢰경계 리셋**(072 codex 교훈 — 내부 코어를 직접 엔드포인트로 승격하면 입력 신뢰경계가
   리셋된다): `query` 길이상한(1..4000)·비공백 검증(422), `limit` 클램프(1..10, 기본 4). 챗에선
   `user_text`(요청 바운드)가 들어오지만 직접 엔드포인트는 임의 입력 → mem0 임베딩 비용 상한 필수.
3. **그래이스풀·정직**: `mem_cfg`가 None(메모리 미구성/비활성)이면 502가 아니라 `enabled=false`+빈
   결과로 응답 — "결과 없음"과 "메모리 미구성"을 UI가 구분(079 "0건도 일어난 일" 원칙).
4. **UI "조회 시험" 드로어 2개**(072 `SearchDrawer` 미러): AgentMemoryPanel·UserMemoryPanel에 각각 슬롯
   (스코프 agentId/userId는 패널이 이미 보유). 쿼리·limit 입력 → 결과를 score 태그·scope·text 카드로.
5. **RBAC 무회귀**(아래 체크리스트) — 기존 메모리 CRUD와 *같은 헬퍼*로 소유권 정렬, 새 경계 0.

## 설계

### 스키마 — `schemas.py` (072 `CollectionSearch*` 옆에, 두 라우터 공유)
```python
class MemorySearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=4, ge=1, le=10)
    @field_validator("query")
    @classmethod
    def _non_blank(cls, v: str) -> str:  # 072 _non_blank와 동일 — strip 후 빈 문자열 거부(422)
        if not v.strip():
            raise ValueError("질의를 입력하세요")
        return v

class MemoryHit(BaseModel):       # memory.search 반환 {type,text,score,scope}
    type: str
    text: str
    score: float
    scope: str                    # 매치된 축 이름(agent_id/user_id/run_id)

class MemorySearchOut(BaseModel):
    query: str
    limit: int
    enabled: bool                 # mem_cfg 확보 여부 — false면 미구성(빈 결과와 구분)
    results: list[MemoryHit]
```

### 백엔드 — 에이전트 (`agents.py`, 기존 `_agent_mem_cfg` 재사용)
```python
@router.post("/{agent_id}/memory/search", response_model=MemorySearchOut)
async def search_agent_memory(agent_id, body: MemorySearchIn, session=Depends(get_session)):
    agent, mem_cfg = await _agent_mem_cfg(session, agent_id)   # 404 if agent None
    if mem_cfg is None:
        return MemorySearchOut(query=body.query, limit=body.limit, enabled=False, results=[])
    hits = await asyncio.to_thread(memory.search, {"agent_id": agent.agent_id}, body.query, mem_cfg, body.limit)
    return MemorySearchOut(query=body.query, limit=body.limit, enabled=True,
                           results=[MemoryHit(**h) for h in hits])
```
- 에이전트 메모리는 *유저 스코핑 아님*(기존 agent-memory CRUD가 router-auth만 — 누구나 큐레이션). 시험도
  그 패턴 상속, 새 principal 게이트 없음. 스코프 dict가 mem0 filter로 들어가 그 agent_id 기억만 로드.

### 백엔드 — 유저 (`memory_routes.py`, 기존 `_assert_principal_may_access`·`_user_mem_cfg` 재사용)
```python
@router.post("/user/{user_id}/search", response_model=MemorySearchOut)
async def search_user_memory(user_id, body: MemorySearchIn, principal=Depends(current_principal),
                             session=Depends(get_session)):
    _assert_principal_may_access(principal, user_id)          # 비-어드민은 자기 user_id만(403)
    mem_cfg = await _user_mem_cfg(session)
    if mem_cfg is None:
        return MemorySearchOut(query=body.query, limit=body.limit, enabled=False, results=[])
    hits = await asyncio.to_thread(memory.search, {"user_id": user_id}, body.query, mem_cfg, body.limit)
    return MemorySearchOut(query=body.query, limit=body.limit, enabled=True,
                           results=[MemoryHit(**h) for h in hits])
```

### 프런트 — api.ts
```ts
export interface MemoryHit { type: string; text: string; score: number; scope: string }
export interface MemorySearchOut { query: string; limit: number; enabled: boolean; results: MemoryHit[] }
export const searchAgentMemory = (agentId, query, limit) =>
  post<MemorySearchOut>(`/agents/${agentId}/memory/search`, { query, limit })
export const searchUserMemory = (userId, query, limit) =>
  post<MemorySearchOut>(`/memory/user/${encodeURIComponent(userId)}/search`, { query, limit })
```

### 프런트 — "조회 시험" 드로어 (072 `SearchDrawer` 미러)
- 공용 `RecallDrawer({ title, onSearch, onClose })` 1개를 만들고 AgentMemoryPanel·UserMemoryPanel이
  각자의 `onSearch`(searchAgentMemory/searchUserMemory 바인딩)를 주입 — UI drift 0.
- 상태: `query`·`limit`(기본 4)·`out: MemorySearchOut|null`·`searching`. 스코프(에이전트/유저) 바뀌면 리셋.
- UI: `<TextArea>` 질의·`<InputNumber min=1 max=10>` limit·`검색` 버튼. `enabled===false`면 "장기 기억이
  비활성/미구성입니다" 안내. 결과는 score `Tag`(소수3)·scope 태그·text 카드. 0건이면 "회상된 기억 없음".
- 각 패널 헤더에 "조회 시험" 버튼 → 드로어 토글.

## RBAC/소유권 경계 스펙 체크리스트 적용 (트리거: user_id/agent_id 메모리 + `_assert_*` 헬퍼)

1. **입구 열거(닫힌 집합)** — 이 스펙이 더하는 입구는 **읽기 전용 2개뿐**: agent search·user search.
   create/update/**delete**/resume/lazy-create/외부프로토콜 입구 **없음**(회상은 부수효과 0, 새 영속 0).
   챗의 회상 경로는 별개 입구로 이미 존재(여기서 새로 만드는 게 아님).
2. **입구별 소유권** — 둘 다 읽기:
   - agent search: 스코프 `{"agent_id": agent.agent_id}`를 mem0 filter에 밀어 그 에이전트 기억만 로드
     (SELECT-WHERE 등가). 에이전트 메모리는 유저 축이 아님 → 기존 CRUD와 동일하게 router-auth만(새 경계 0).
   - user search: `_assert_principal_may_access(principal, user_id)`로 **비-어드민은 자기 user_id만**(403),
     스코프 `{"user_id": user_id}`를 filter에 밀어 그 유저 기억만. 비-SQL 저장소(Mem0/pgvector)라
     SELECT-WHERE 불가 → **소유권을 호출의 filter에 묶고**(check-then-act 아님) principal 게이트를 검색 전에.
3. **단일 헬퍼** — 새 소유권 헬퍼 0. `_assert_principal_may_access`(유저)·`_agent_mem_cfg`(에이전트)를
   기존 CRUD와 **그대로 공유** → 드리프트 0.
4. **존재 비노출** — agent는 `_agent_mem_cfg`가 404. user는 기존 `_assert_principal_may_access`의 403
   (주체×대상 이진 게이트 — 대상 존재 여부와 무관히 403이라 존재 오라클 아님). 검색엔 mem_id 입력이
   없어 row-레벨 열거 오라클(068) 자체가 없음. 기존 유저-메모리 라우트(list/update/delete)와 동일 패턴.
5. **검증 사다리 3런(비겹침)**:
   ① 단위 — query>4000 또는 공백 → 422; limit 클램프(0·11 → 422); mem_cfg None → enabled=false·빈결과;
      비-어드민이 타 user_id → 403; 스코프 격리(agent A 검색이 B 기억 미반환).
   ② 실인프라 통합 — seed mem0 + 실제 검색: 소유 스코프 회상 hit 반환·교차유저(비-어드민) 403·
      교차에이전트 격리. (가능 시 임베딩 백엔드 실호출, 없으면 graceful enabled=false 경로 단언)
   ③ 적대 codex — "보장 목록의 여집합": 비-어드민이 타 유저 메모리를 검색할 길이 있나·길이상한 우회·
      limit 클램프 우회·agent 검색이 교차 에이전트/유저로 새나·enabled 거짓양성.
6. **자가-잠금 핀**(070) — 조임이 *정당한 본인 접근*을 막지 않는지 별도 단언: 비-어드민이 **자기** user_id
   검색 → 200(403 아님), 어드민은 임의 user_id → 200.

## 검증 결과 (3런)
`tests/verify_084_memory_search.py` — **47/47 PASS (VERIFY084_OK)**.

- **① 단위(인프라 불요, 35건)** — 스키마 422(공백·빈·query>4000·limit 0/11, 경계 4000·1·10 OK, 기본 4,
  양끝 트림); RBAC 게이트(member→타 user_id 403 / member→본인 통과=self-lock 핀 / 머신·superuser·casbin-admin→임의
  통과); 스코프 격리(agent 검색=agent 기억만·user 누출 0 / user=alice만·bob·agent 누출 0, hit 구조 {type,text,score,scope});
  graceful(미가용→enabled=false·[]); agent 404; 핸들러 회상(백엔드 존재→enabled=true·자기 스코프만);
  `recall_probe` facade(미가용=None vs 가용·0건=[] 구분 + 과다반환 limit 슬라이스).
- **② 실인프라 통합(in-process ASGI + 실 DB, 12건 + 라운드트립)** — 라우트 등록; HTTP 계층 422(공백·빈·>4000·limit 0/11,
  경계 통과); 토큰 없음 401; 없는 agent 404; 실검색 200·응답 형상. **실 mem0 라운드트립**: agent에 `add` 201 →
  시맨틱 질의("보고서 형식이…?")가 저장 사실("보고서는 한 줄 요약으로 시작…")을 **score 0.843·scope=agent_id**로 회상(시험 후 삭제로 시드 무오염).
- **③ 적대 codex** — 4건 제기, 비판 검토 후: **P1/P3(에이전트 검색 비-어드민 접근·존재 오라클)=설계상 의도** — 형제
  `GET /agents/{id}/memory`(list)와 동일 패턴(같은 `_auth` 라우터 게이트·같은 agent_id 스코프·read-only), 신규 노출 0이며
  principal 등급은 admin API 전체의 선재 속성(084 밖). **P2a(구성됐으나 깨진 백엔드를 "회상 0건"으로 위장)·P2b(백엔드 limit
  무시 시 무방어)=유효 → 수정**: `memory.recall_probe`를 신설해 `enabled`를 *백엔드 가용성*(resolve_backend)에 묶고
  방어적 `[:limit]` 슬라이스, chat 경로(`search`)는 무변경(drift 0). U4 P2a·U7 P2b 회귀 핀으로 잠금.
- **브라우저(시스템 Chrome, `tests/browser/shot-recall-084.mjs`)** — 메모리 화면 양 탭에서 드로어 개방·실 엔드포인트 질의 확인.
  **양성**: agent 탭이 회상 카드 1건 렌더(`회상 1건`·#1·관련도 0.845·agent_id·semantic). **음성/공백**: 기억 없는 스코프는
  enabled=true + "회상된 기억이 없습니다"(미가용 Alert와 구분). 콘솔 무관 경고(antd width/message deprecation)만.
- **tsc**: `admin && npx tsc --noEmit` → 0.

## 완료 체크
- [x] 백엔드 2 엔드포인트(agent/user) — 공유 코어 직접 호출, enabled 정직(`recall_probe`로 백엔드 가용성에 묶음)
- [x] 입력 검증(query 1..4000·비공백·limit 1..10), 미가용 graceful(enabled=false)
- [x] api.ts 클라이언트 2개 + RecallDrawer 공용(두 패널 슬롯)
- [x] RBAC: 비-어드민 타유저 403·자기 200·교차에이전트/유저 격리, 기존 헬퍼 재사용 무회귀
- [x] 단위 + 실인프라 통합 + 적대 codex 그린, tsc 0, 브라우저 양성·음성
