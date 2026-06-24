# 021 — mem0의 가치는 memory_type이 아니라 스코프·추출·엔티티그래프

맥락: "mem0 메모리 기능 파악" → 카탈로그의 4종(단기/의미/일화/절차)을 mem0 기능으로 오해.
대상: `packages/api/src/api/memory.py`, `chat.py`, `seed.py`. mem0 2.0.7.

## 함정 — 부분 구현을 보고 "이 라이브러리 이점이 없다"고 단정

처음 소스만 읽고 "mem0가 선언한 3종(semantic/episodic/procedural) 중 1종만 구현 → mem0가 홍보하는
이점을 못 누린다"고 결론냈다. **틀렸다.** mem0 2.0.7 `MemoryType` enum을 봐도:
- `PROCEDURAL`만 실 코드 경로(`_create_procedural_memory`, agent_id 필요).
- `EPISODIC`는 enum 정의뿐(구현 0, `add`가 `Mem0ValidationError`로 거부).
- `SEMANTIC`은 그냥 `add` 기본 동작(파라미터 없음).

즉 **memory_type 스위치는 mem0의 가치 명제가 아니다.** 그걸 기준으로 "이점 없음"을 판단한 게 오류.

## 교정 — mem0의 실제 가치 명제 (웹·소스 대조)

1. **추출/통합 파이프라인**: `infer=True`(기본) — LLM이 대화에서 사실을 추출하고 dedup(ADD/UPDATE/
   DELETE/NOOP). 원문 저장이 아니라 "사실"을 만든다.
2. **다층 스코프**: `user_id`(세션 가로지름) / `agent_id`(에이전트 전용) / `run_id`(세션). 한 기억을
   여러 축에 태깅하고 축별로 회상.
3. **자동 엔티티 그래프**: 신버전 mem0는 외부 graph_store(Neo4j 등)를 제거하고 `{collection}_entities`
   내장 엔티티 링킹으로 대체 — `add()` 시 자동.

우리 프로젝트는 (1)·(3)을 이미 받고 있었다. 진짜 공백은 **3개 스코프 축을 단일 `user_id`로 접은 것**.
→ 스펙 020에서 user/session 다층으로 펼침.

## 두 가지 일반화

- **인기 외부 라이브러리의 "이점"은 소스의 기능 enum이 아니라 가치 명제에 있다.** 부분 구현된 enum을
  보고 전체를 폄하하면 오판한다. **공식 문서·실사용 사례(웹)로 가치 명제를 먼저 잡고**, 소스로
  "우리가 그 가치를 받고 있는가"를 검증하는 양방향 대조를 한다. (사용자 지시 "소스 말고 웹에서 사례를
  찾아라"가 이걸 강제했다.)
- **mem0 필터는 AND.** 여러 축을 한 질의에 넘기면 교집합이라 합집합 회상이 안 된다 → **축별 단일 검색
  후 병합**. 그리고 풍부 태깅 + 부분집합 필터는 **누출 위험**(남의 user 기억이 타 세션에 회상)을 만든다
  → **쓰기 축 = 사실의 소유자**(유저 턴은 user_id+run_id만, agent_id 미사용)로 차단. [[019-mem0-memory-scoping]] 공백
  함정과 동형: 경계의 의미를 추측 말고 소스로 확정.

## 곁다리 — 외부 함수 키워드 인자는 소스로 확인

mem0 2.0.7 `search(query, *, top_k=20, filters=...)`. `limit=`을 넘기면 `**kwargs`로 삼켜져 **무시**되고
매 축 20개를 끌어온다(출력은 후처리 `[:limit]`로 맞아 happy path에 가려짐). → `top_k=limit`. 외부 SDK
호출 인자는 **`inspect.signature`/소스로 키워드까지 선확인**([[020-pgvector-shared-backend-and-dsn-delegation]]에
이미 적었던 교훈을 또 놓침 — 이번엔 타자 검증이 잡음).

관련: 회고 [[011-mem0-multi-scope-and-catalog-realign]] · 스펙 docs/spec/020 · [[019-mem0-memory-scoping]] · [[009-mem0-local-mlx-integration]]
