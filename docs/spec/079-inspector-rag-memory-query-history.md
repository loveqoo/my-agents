# 079 — 인스펙터에 RAG 문서검색 · 메모리 조회 이력 노출 (이슈 5)

## 배경

사용자 보고: "플레이그라운드 인스펙터에 tag 조회, 메모리 조회에 대한 이력 안 보임."
사용자 결정(AskUserQuestion): **"RAG 문서검색 + 메모리 둘 다"** — "tag 조회"=RAG 문서 검색,
"메모리 조회"=mem0 회상. 두 조회의 *이력*(무엇으로·무엇에 대해·몇 건)을 인스펙터에 드러낸다.

## 현 배선 (실측 — 추측 금지)

- **메모리 회상**: `event_stream`이 턴 시작에 `memory.search(recall_scope, user_text, mem_cfg)`로
  `mem_hits`를 얻고(chat.py:522), `assemble_trace(memories=mem_hits)`로 `trace["memories"]`에 싣는다.
  `trace["memoryScope"]`(None 아닌 축)도 싣는다(chat.py:636). **그러나 회상 *쿼리*(user_text)는
  어디에도 안 담긴다.** Inspector 메모리 Section은 회상 hit를 렌더하지만(Inspector.tsx:291-317),
  **0건이면 "메모리 타입: …" + count 0뿐 — 조회가 일어났다는 흔적이 없다.**
- **RAG 검색**: `build_rag_tool`이 도구 호출을 `calls_sink`에 기록한다 — `server="rag"`,
  `tool="search_documents"`, `args={query, top_k}`, `result`, **`hits`**(runtime.py:302-313). 이게
  `trace["mcp"]`에 들어간다. chat.py는 추가로 `trace["ragCollections"]`(구성된 컬렉션명, :630)·
  `trace["ragUnresolved"]`(요청됐으나 미해석, :633)를 싣는다. **그러나**:
  - Inspector는 RAG 호출을 MCP Section에 섞어 보여 *구분이 안 된다*(Inspector.tsx:319-325).
  - `McpCall`은 args/result/ms만 그리고 **`hits`를 안 쓴다**(:110-139).
  - **`ragCollections`/`ragUnresolved`는 Inspector가 아예 렌더하지 않는다** → 에이전트가 도구를
    안 부르면 RAG가 *연결돼 있었는지조차* 안 보인다.

→ 결국 "조회의 *행위*"(쿼리·대상·건수)가 *결과가 비면* 사라진다. 사용자가 "이력 안 보임"으로 느낀 지점.

## 목표 (완료 조건 — 측정 가능)

1. **메모리 조회 이력**: 회상이 수행됐으면(used_memory) 그 **쿼리**와 **회상 건수**를 인스펙터에
   표시한다 — **0건이어도** "조회 «쿼리» → 0건 회상"을 보여 조회가 일어났음을 드러낸다. 기존 hit
   목록·스코프 표시는 유지.
2. **RAG 문서검색 이력**: 인스펙터에 **전용 "문서 검색 (RAG)" 섹션**을 둔다 —
   (a) 구성된 컬렉션(`ragCollections`)을 태그로, (b) 미해석(`ragUnresolved`)을 경고로,
   (c) 실제 검색 호출(쿼리·`hits`·result)을 **0건이어도** 표시. MCP 섹션에서는 rag 호출을 빼
   중복을 없앤다.
3. 무회귀: RAG/메모리 미사용 에이전트(code/external 등)의 인스펙터는 기존과 동일(섹션 자동 숨김).

## 조치

### 백엔드 (chat.py) — 메모리 쿼리만 추가(나머지는 이미 trace에 있음)
- `event_stream` 메인 경로: `used_memory`면 `trace["memoryQuery"] = user_text[:300]`
  (회상에 쓴 쿼리; 표시·길이상한). memoryScope 인접(chat.py:634-636)에 추가.
- 승인대기 `pending_trace`(chat.py:605-610): 일관성 위해 `used_memory`면 동일 키 추가.

### 프론트 — 타입 (agentData.ts)
- `McpCallT`에 `hits?: number`.
- `Trace`에 `memoryQuery?: string`, `ragCollections?: string[]`, `ragUnresolved?: string[]`.

### 프론트 — Inspector.tsx
- **메모리 Section**: `t.memoryQuery`가 있으면 상단에 "조회 «query» → N건 회상" 줄(0건도 표시).
- **새 "문서 검색 (RAG)" Section**(MCP 위/아래): 조건부 렌더
  (`ragCollections?.length || ragUnresolved?.length || rag호출 존재`).
  - 구성 컬렉션 태그, 미해석 경고, RAG 호출 카드(쿼리·hits·result·ms·status).
- **MCP Section**: `t.mcp.filter(c => c.server !== 'rag')`만 렌더(중복 제거), count도 그 기준.

## 검증

- **타입**: `tsc --noEmit`(admin) 무에러.
- **백엔드**(서브에이전트/스크립트 또는 단위): used_memory 턴 trace에 memoryQuery=user_text 포함,
  rag 컬렉션 구성 시 ragCollections 노출(이미 동작 — 회귀 확인). 0건 회상도 memoryQuery 유지.
- **브라우저**(Playwright + 시스템 Chrome): RAG 컬렉션 연결 + 메모리 활성 ui 에이전트로 한 턴
  보내고 인스펙터에서 ① 메모리 섹션 "조회 … → N건", ② "문서 검색 (RAG)" 섹션에 컬렉션 태그/검색
  호출(hits) 렌더 캡처. RAG/메모리 없는 에이전트로 두 섹션 숨김(무회귀) 캡처. antd6 클래스는 learning 080.
- **거짓초록 방지**: 셀렉터 0개=측정 실패로 다룸(learning 080·035).

## RBAC 체크리스트 적용 여부

**경계 검토 필요** — 회상 쿼리(user_text)·메모리 hit는 *유저 데이터*다. 단 이 스펙은 **표시 전용**:
trace는 이미 해당 턴의 회상 결과를 담아 같은 응답 스트림으로 *그 요청 주체에게* 돌아간다(새 입구·
교차유저 조회 없음). memoryQuery는 *방금 그 유저가 보낸* user_text의 에코일 뿐 — user_id 스코프·
소유권 경계 불변(SELECT-WHERE·owner 스탬프 미접촉, 새 자원 입구 0). mem0 회상의 스코프 가드는
기존 recall_scope(user_id+run_id+agent_id)가 이미 보유(스펙 018/053). → 경계 *이동 없음*, 표시층만.

## 완료 체크
- [x] 백엔드 trace["memoryQuery"](메인+pending) — 회상 쿼리 에코, 길이상한
- [x] agentData.ts 타입(McpCallT.hits, Trace.memoryQuery/ragCollections/ragUnresolved)
- [x] Inspector 메모리 "조회 → N건"(0건도) + 전용 RAG 섹션(컬렉션·미해석·hits) + MCP에서 rag 제외
- [x] tsc 무에러 + 브라우저(RAG/메모리 에이전트 두 이력 렌더·미사용 에이전트 두 섹션 숨김)

## 검증 결과 (2026-06-30)
- `tsc --noEmit`(admin) 무에러.
- 브라우저(`tests/browser/shot-rag-memory-079.mjs`, Playwright+시스템 Chrome) **RAG079_PASS**:
  - 양성(Research Assistant, mem0+docs_kb/product_titles): 회상 조회 블록(쿼리 에코 + "0건 회상"
    — **0건이어도 조회 행위 노출**), 문서 검색(RAG) 섹션(연결 컬렉션 태그 2 + search_documents
    호출 카드 "3건"·52ms·결과). MCP 섹션은 rag 제외 → "호출된 도구 없음"(중복 제거 확인).
  - 음성(Doc Translator, code·단기만): 회상 조회·RAG 섹션 둘 다 0(무회귀 확인).
