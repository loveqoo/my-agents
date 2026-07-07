# 스펙 233 — 에이전트 능력×타입 조합 전수 테스트 매트릭스

## 배경 (사용자 지시 2026-07-08)

"에이전트의 각 도구·기능·타입의 경우의 수를 계산하고 모든 조합을 테스트하라. 성공할 때까지 수정·반복."
근거 사건: 스펙 201 후속2(회고 188) — 위키 도구가 **능력 부여됐고 도구 단위테스트는 초록인데, 실제
저장된 에이전트가 대화 중 발동을 안 함**(배선 부재). 부품 테스트(verify_201=도구 함수 직접 호출)는
이 틈을 못 본다. 필요한 건 **"실 저장 config로 채팅 관통 시 능력이 진짜 발동하는가"**의 조합 전수.

## 축 열거 (코드 정본)

### 축1 — impl 타입 8종 + `consumes`(실제 읽는 설정 표면, 스펙 206, runtime.py)
| impl | consumes |
|---|---|
| `default`(ReAct, impl 미선언) | mcps, vectorTables, memories |
| `plan_execute` | mcps, vectorTables, memories |
| `route` | memories |
| `orchestrate` | capabilities, memories |
| `orchestrate_ranked` | capabilities, memories |
| `artifact_slotfill` / `artifact_targeting` / `artifact_form` | artifactSpec |

### 축2 — 기능(capability kind) 6종 (broker.py CAP_KIND_*)
agent(A2A 하위)·mcp(도구)·rag·memory(읽기)·memwrite·memedit

### 축3 — 도구(mcp 내부): web-fetch=`wiki_search`·`wiki_page`, local-tools=`delete_record`(HIL), calc-tools
### 축4 — source 3종: ui·code·external(A2A)

### 능력→설정 표면 매핑 (발동 경로)
- 직접 배선: mcp→`config.mcps`, rag→`config.vectorTables`, memory→`config.memories`
- 브로커 배선(orchestrate만): 6종 전부→`config.capabilities`(형식: `mcp:server[/tool]`·`rag:col`·
  `memory|memwrite|memedit:user`·`agent:agt_…`)

## 경우의 수 (핵심 매트릭스 = impl 8 × 기능 6 = 48칸)

각 칸은 impl의 consumes가 그 능력의 표면을 포함하느냐로 **발동/무시**가 갈린다:

- **발동해야 함 = 19칸**: default 3(mcp·rag·memory) + plan_execute 3 + route 1(memory) +
  orchestrate 6 + orchestrate_ranked 6 + artifact 0.
- **무시→경고해야 함 = 29칸**: 나머지(예: route+mcp, artifact+rag, default+memwrite). impl이 안 쓰는
  능력을 배선하면 조용히 삼키지 말고 "무시됩니다" 경고 + RuntimeMeta.consumes가 그 표면 제외를 확인.
- artifact 3종은 별도(artifactSpec 구동 산출물) — 능력 6종엔 0발동이 정답.
- 도구 세부(wiki_search/wiki_page/mock delete_record)·source(external=A2A)는 발동칸에 곱해 확장.

## 테스트 설계 (verify_110 패턴 확장 — **오버라이드 금지, 실 저장 경로**)

`tests/verify_233_capability_matrix.py` — httpx.ASGITransport(app) 인프로세스, 슈퍼principal override,
POST /agents(실 저장) → POST /agents/{id}/chat 1턴 → 최종 trace JSON 단언 후 삭제.

**발동 신호(trace 필드)**: `graph`=노드열(`broker_invoke:{kind}`)·`mcp`=calls_sink(도구·RAG 호출)·
`memories`=회상 hit. **결정성**: orchestrate 위임=LLM 독립. ReAct 도구=mock-llm `_TOOL_TRIGGERS`
(rag→"검색", mcp delete_record→"삭제").

칸별 단언:
- 발동칸: 해당 신호 존재 + (가능하면)근거 답 + mock 미대체.
- 무시칸: 신호 부재 + `/agents/runtimes` RuntimeMeta.consumes가 표면 제외.
- 위양성 배제: 능력 0개 대조(broker_invoke 없음, verify_110 H3).

## 실측 결과 (2026-07-08) — 예측 19/29 → **실제 발동 22 / 무시 26**

예측(19/29)은 memory가 impl별로 게이트된다는 가정이었으나 **틀렸다**. 실측으로 정정:

### 발견 1 — memory 회상은 **플랫폼 레벨**(impl 무관), consumes는 런타임 게이트 아님
`config.memories`가 켜지면 회상 선처리(chat.py `used_memory = memory_enabled(config.memories) AND mem_cfg`)가
**impl 실행 전** 돌아 유저 기억을 컨텍스트에 주입한다 — `consumes`(스펙 206: 폼 힌트일 뿐)와 무관.
그래서 artifact(consumes=artifactSpec, "memory 안 씀" 선언)도 `config.memories`를 실으면 회상한다.
→ memory 열은 **전 impl 발동**(22칸 = 기존 19 + artifact×3 memory). "기능이 impl별로 게이트된다"는
가정은 memory엔 안 맞는다. 보안 문제 아님(유저 본인 기억, per-user). 폼은 표면을 숨겨 오배선을 막지만
런타임은 강제 안 함.

### 발견 2 (codex 적대 검증, 2라운드) — 자가 초록에 숨은 false-green 3건 적발·봉합
1. **broker_invoke 노드 존재 ≠ 성공**: 브로커는 provider가 error여도 노드를 남긴다 → 노드만 보면
   "시도됨"을 "동작함"으로 오판. **봉합**: `brokerCalls`의 error 없음 + rag는 hits 필드까지 단언.
2. **artifact memory를 브로커 표면으로 우회**해 IGNORE 판정(실 표면 config.memories 미검증). **봉합**:
   실 표면으로 배선 → 발견 1로 이어짐.
3. **memory 회상 hit의 vacuous pass**: 유저 단위 공유라 앞 셀 프라이밍 누수로 config.memories 없이도
   참 가능. **봉합**: 전 impl 무능력 대조군이 "스토어에 콘텐츠 있어도 config.memories 없으면 회상 0"을
   증명(발동은 누수 아닌 config.memories가 원인).

최종 그리드: **PASS=30(발동 22 + 대조 8) + IGNORE-OK=26 = 48칸**, VERIFY233_OK. 제품 결함(201류 미발동)
**0건** — 배선된 능력은 실 저장·채팅 관통에서 전부 발동한다(발견 1은 결함 아닌 설계 특성).

## 완료 조건
- 48칸 전부 기대대로(발동칸 발동·무시칸 미발동) + 대조 초록. 인프라 게이트(mem0 미설정 등)로 못 도는
  칸은 **정직히 SKIP 표기**(silent 금지, [[cap-the-raw-source-not-the-buffer]] 정신).
- 실 제품 결함 발견 시(201류) 수정→재실행 Ralph 루프, 전부 초록까지.
- codex 적대 검증(하네스가 발동을 위장 통과 안 하는지 — 무위임에도 초록 나는 위양성).

## 검증 사다리
① 하네스 자체 로직 ② 인프로세스 실 DB 관통(seed+app) ③ codex 적대(여집합: "발동 안 했는데 초록").
