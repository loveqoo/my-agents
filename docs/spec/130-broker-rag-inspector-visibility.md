# 130 — 조율형의 RAG 검색을 인스펙터에 표면화 (보이지 않던 검색)

## 배경 / 왜
사용자: "옵시디언 매니저(조율형)가 RAG 검색을 안 한다." e2e 진단(deep-reasoner) 결과 **검색은 실제로
동작** — 라이브 트레이스에 `broker_invoke:rag:Obsidian` 기록·답변이 데이터 인용. 문제는 **표시 구멍**:
인스펙터의 "문서 검색 (RAG)" 섹션은 직접형 배선(`ctx.rag_collections`·`t.mcp server='rag'`)만 채우고,
**조율형의 브로커 경유 RAG 호출은 아무 표시가 없다**(신호는 그래프 노드명뿐). + 히트가 약해 "자료에
없음"이라 답한 턴은 "검색 안 함"으로 오인된다.

## 설계

### 백엔드 (검색 메타를 구조화해 트레이스로)
1. **RagProvider.invoke**: 성공 시 `raw`에 `hits`(건수)·`topScore`(최고 유사도) 추가
   (broker.py:600 부근 — hits는 이미 손에 있음, 포맷 문자열에서 파싱하지 않고 구조화).
2. **PolicyScopedBroker.invoke** 이력(:1085): invocation 엔트리에 `raw`의 hits/topScore(있으면)와
   `error`(불리언) 통과 — `{"node","cap_id","ms","hits"?,"topScore"?,"error"?}`.
3. **chat.py**: 기존 graph 노드 합류(무변경)에 더해, invocations가 있으면
   `trace["brokerCalls"] = [{capId, ms, hits?, topScore?, error?}]` 추가. 위임 없던 턴은 필드 자체가
   없음(무회귀). 승인대기(pending_trace) 경로는 OUT(선행 cap 노출은 후속).

### 프론트 (인스펙터)
4. `agentData.ts` Trace에 `brokerCalls?` 타입 추가.
5. Inspector "문서 검색 (RAG)" 섹션 확장: `brokerCalls` 중 `capId`가 `rag:`로 시작하는 항목을 렌더 —
   `rag:Obsidian — 검색 4건 · 최고 유사도 0.850 · NNNms`. 판정 태그:
   - `topScore < 0.5`(RetrievalTestPanel green 임계와 동일) → **"관련도 낮음"** 경고 태그(약한 히트 =
     "자료에 없음" 답의 이유가 보임).
   - `hits == 0` → "0건" / `error` → "검색 실패" 태그.
   - 섹션 노출 조건에 brokerCalls(rag) 포함(조율형 턴도 섹션이 뜨게).
6. 비-RAG 브로커 호출(mcp/agent/memory) 표면화는 OUT — 그래프 노드로 이미 보이고, 사용자 문제는 RAG.

## 검증
- verify_130: 실 컬렉션(Obsidian)으로 RagProvider raw에 hits/topScore 존재·broker.invocations 통과·
  0건 질의 시 hits=0·에러 시 error=True.
- 브라우저(fast-worker): 플레이그라운드에서 **옵시디언 매니저에게 실제 질문**(A/B 테스트 — 노트에 있는
  내용) → 응답 후 인스펙터에 "문서 검색 (RAG)" 섹션 + `rag:Obsidian`·건수·유사도 표시(사용자 시나리오
  그대로의 e2e). 직접형 턴 무회귀(기존 섹션 유지).
- codex 적대: raw 통과가 비밀/과대 데이터 안 싣나·무위임 턴 무회귀·프론트 조건 겹침.

## 비목표 (OUT)
- 답변 본문에 "관련도 낮음" 주입(챗 출력 변경) — 인스펙터 표면화로 충족, 본문은 후속 논의.
- 승인대기 턴의 선행 cap 표시, 비-RAG 브로커 호출 상세, 머신 토큰 경고.
