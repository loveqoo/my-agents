# 359 — 노드형 회상 내용 인스펙터 표시 (RAG와 대칭 복원)

## 왜 (실물 확증 — 사용자 신고 + 전수조사)

플레이그라운드 인스펙터에서 노드형(agent-flow) 에이전트의 메모리 **회상 내용이 안 보인다**. "mem 4"처럼
건수는 뜨는데 무엇을 읽었는지 볼 수 없고, 회상된 텍스트는 시스템 프롬프트에 주입돼 **"전송 프롬프트"
탭에만** 나타난다("실행흐름에 있던 메모리가 프롬프트쪽에 보인다"). 반면 **쓰기(자동 저장)와 RAG
검색은 내용이 보인다** — 비대칭.

**근인**: 노드형 회상은 `_MemoryRecallProxy`(chat.py:164)를 쓰는데, 이 프록시는 회상 내용
(`format_memory_hits(hits)`)을 계산해 **프롬프트엔 주입**하지만 트레이스 record엔
`{node, query, hits, cached}`만 남기고 **내용(hits)을 버린다**(chat.py:194). 그래서 인스펙터의 노드형
회상 블록(Inspector.tsx:451)은 카운트+쿼리만 렌더한다.

**회귀 아님, 처음부터의 비대칭**: `memoryRecalls`는 스펙 268에서 도입된 이래 내용 필드가 없었다.
"예전엔 보였다"는 사용자의 에이전트가 예전엔 표준/ReAct 그래프(retrieve_memory 노드 → `t.memories` →
MemoryRow로 내용 표시)였고 지금은 노드형이기 때문. 같은 스펙 268이 두 절반을 다르게 지었다:
- **RAG(P1) = 도구**: 컬렉션별 검색 도구가 결과를 calls_sink에 기록할 때 `hitsDetail`(내용)까지 실어
  RagCall/HitCard가 내용을 보여줌(runtime.py:613).
- **메모리(P2) = 프록시**: 행위(node·query·hits·cached)만 기록, 내용은 버림.

즉 노드형 확장 때 RAG는 "도구=내용 기록" 관례를 물려받았고 메모리만 "프록시=행위만 기록"이라 내용이
빠졌다. **비대칭은 메모리에 국한**(RAG·쓰기·표준읽기는 정상).

## 설계 — 프록시 record에 회상 히트를 실어 표준 경로처럼 MemoryRow 렌더

`memory.search`는 히트를 **프론트 `Memory` 형태 그대로** 반환한다(`{text, score, scope}`,
mem0_backend.py:274) — 표준 경로 `t.memories`가 이걸 그대로 싣는다. 프록시도 같은 히트를 갖고 있으니:

1. **백엔드(`_MemoryRecallProxy`)**: 캐시를 `(text, hits)`로 확장(현재 `(text, n)`), record에
   `"memories": hits`(= `{text, score, scope}` 리스트) 추가. 프록시가 메인·재개 경로 공유이므로
   **한 곳 수정으로 chat.py 회상·chat_approval 재개 회상 둘 다 해결**.
2. **프론트 `Trace` 타입**: `memoryRecalls`에 `memories?: Memory[]` 추가.
3. **인스펙터(Inspector.tsx:451)**: 각 recall 행 아래에 `(r.memories ?? []).map(m => <MemoryRow m={m}/>)` —
   **표준 retrieve_memory 경로와 같은 컴포넌트**(drift 0). 노드 행에 "무엇을 읽었나"가 복원된다.

**마스킹 정합(비신규 노출)**: 쿼리는 지금처럼 `_sanitize`(앞 노드 출력이라 비밀 가능). **회상 내용은
사용자 자기 스코프의 저장 기억**이고 표준 경로(`t.memories`)가 이미 무마스킹으로 보여주므로 파리티 —
새 노출 아님. (RAG hitsDetail도 문서 본문을 그대로 보여주는 것과 동형.)

**노드형은 `t.memories`=[]**(chat.py 선조회 안 함) — retrieve_memory 블록은 안 뜨고 memoryRecalls
블록만 뜬다(이중 렌더 없음). 캐시 공유(cached=true) 행도 내용을 실어 **각 노드 행이 자기완결**
(재검색은 캐시로 1회 수렴하되, 표시는 노드별로 "이 노드가 무엇을 봤나"를 온전히).

## 완료 조건 (수치)

- **N1** 회상 후 프록시 record에 `memories`가 `{text, score, scope}` 리스트로 존재(비어있지 않은 회상).
- **N2** 재개 경로도 동일(같은 프록시) — resume_recalls record에 memories 존재.
- **N3** 인스펙터 노드형 회상 노드에 MemoryRow로 회상 내용 렌더(다해상도 스샷: wide 1500·mid 1100·narrow 768).
- **N4** 마스킹 파리티 — 쿼리 마스킹 유지, 내용은 표준 경로와 동일(새 마스킹 없음), tsc 0.
- **N5** 무회귀 — 표준 retrieve_memory 경로·RAG·쓰기 표시 불변, `make test` 씨앗 그물 SUITE_OK.

## 결과 (2026-07-15)

- `_MemoryRecallProxy`(chat.py) record에 `memories`(회상 히트) 추가 — 프록시 공유라 메인·재개 경로
  동시 해결. 프론트 `memoryRecalls` 타입에 `memories?: Memory[]`, 인스펙터 노드형 회상 블록에
  표준 경로와 같은 `<MemoryRow>` 렌더.
- **N1/N2 단위**: verify_268_per_node.py — record가 `{text,score,scope}` 회상 히트 보유, 캐시 공유
  행도 내용 자기완결, hits 카운트=memories 길이. 27/27 통과.
- **end-to-end(실서버 SSE)**: verify-pipeline-268.mjs — 실 chat 트레이스의 `memoryRecalls[].memories`에
  `{text:"…", score:0.508, scope:"user_id"}` 실림(기억확인·마무리 두 노드, 캐시 공유 행 포함). RAG P1
  단언 3건은 mock 모델 도구호출 브리틀니스(내 변경과 무관, 별개).
- **다해상도 스샷**: shot-recall-content-359.mjs — 실행흐름 기억확인·마무리 노드에 MemoryRow로 회상
  내용 렌더(예전엔 "기억 회상 1건"만). wide(1500)·mid(1100)·narrow(768) 전부 깨짐 0, 드로워도 정상.
- **무회귀**: `make test` 씨앗 그물 SUITE_OK(경합 없이 재실행 — rc=143 1건은 API서버·브라우저 동시
  부하로 verify_111 mem0 왕복이 타임아웃한 경합, 단독 통과 확인). tsc 0.

## OUT

- 위임(브로커) 하위 실행 흐름의 `memory:used` 태그 → 내용 표시(하위트레이스의 의도적 거친 요약, 별개).
- 회상 텍스트가 시스템 프롬프트에도 나타나는 것(전송 프롬프트 탭) — 정상(주입이 실제로 일어나므로),
  실행흐름에 내용을 복원하면 "프롬프트쪽에만 보임" 불만은 해소됨.
