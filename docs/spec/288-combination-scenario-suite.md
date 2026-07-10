# 288 — 기능 조합 시나리오 스위트 (실모델 전제)

## 배경

- 루프 ~300회 동안 기능을 개별 검증(verify_NNN ~120개·browser e2e)해 왔지만, **기능 조합**
  (기억×도구×세션×오버라이드×impl)을 한 번에 도는 회귀망이 없다. 사용자: "기능을 충실히 다져온
  만큼 기능 조합에 대해 신뢰감이 있어야 한다."
- 이 스위트는 다음 작업(파이썬 코드 대정리)의 **안전망**이다 — 스위트가 초록이면 리팩터링이
  조합을 깨지 않았다고 믿을 수 있어야 한다.
- **실모델 전제**(사용자 결정 2026-07-10): mock이 아니라 실제 chat/embedding 모델로 돈다.
  실모델이 없으면 스위트는 동작하지 않는다(정직한 중단, 빈 초록 금지).

## 목표 (완료 기준 — 측정 가능)

1. **한 명령 실행**: `uv run --project packages/api python tests/suite/run.py` 가 프리플라이트 →
   픽스처 부트스트랩 → 시나리오 전수 → 종합 리포트+종료코드(전부 통과 0 / 실패 1 / 사전조건 미충족 2).
2. **프리플라이트(사전조건 게이트)**: DB(pgvector) 접속, **실모델 존재·응답**(chat 1개+embedding 1개,
   `provider_kind != mock`, 실제 1회 핑) 확인. 미충족이면 무엇이 없는지 말하고 exit 2.
3. **픽스처 멱등**: 부트스트랩을 2회 연속 실행해도 두 번째는 생성 0건(이름 기준 get-or-update),
   suite 픽스처 개수 불변. DB를 새로 세워도 같은 명령 한 번으로 복원.
4. **매트릭스 커버리지**: impl 6종(직접·pipeline·orchestrate·route·plan_execute + 비영속 변주) ×
   축 4개(도구/기억/세션·영속/오버라이드)를 아래 매트릭스대로 **최소 30개 시나리오**, 전부
   **기록 기반 단언**(응답 문장 정확일치 단언 0건).
5. **재실행 안전**: 전체 스위트 연속 2회 실행 모두 초록(시나리오 간·회차 간 상태 오염 없음).
6. 전체 실행 목표 **10분 이내**(실모델 기준, 로컬 모델 속도에 따라 변동 — 초과 시 리포트에 명시만).

## 원칙

- **단언은 기록으로, 주장은 믿지 않는다**(learning 151 — 모델은 "호출한 척" 환각): 도구 호출은
  trace의 `mcp`·`toolDiag.called`, 위임은 `brokerCalls`, RAG는 `ragCollections`+`/rag/{cid}/search`,
  기억 회상은 `used_memory`+회상 진단(`POST /memory/user/{id}/search`의 `diag.stored/count`),
  영속성은 DB 행 수 실측(verify_235 패턴). 응답 텍스트 단언은 "특정 토큰 포함"(예: 이전 턴에 준 숫자)
  까지만 허용 — 문장 일치 금지.
- **오버라이드를 1급 검증 수단으로**(사용자 지시): 조합 축의 절반은 픽스처를 늘리는 대신 base
  에이전트 + `overrides`(세션 한정)로 만든다. 이러면 조합 검증과 오버라이드 기능 검증이 한 번에 된다.
  단, 오버라이드 무시 회귀를 잡기 위해 **저장 설정으로 같은 조합을 검증하는 대조 시나리오**를 축마다
  최소 1개 둔다(오버라이드가 조용히 무시돼도 초록이 되는 함정 방지).
- **시나리오 독립**: 시나리오마다 새 세션. 한 시나리오 실패가 다음을 오염하지 않는다.
  실모델 간헐 실패 대비 시나리오 단위 1회 재시도(재시도로 통과 시 리포트에 `flaky` 표기 — 숨기지 않음).
- **consumes 정합**(learning 152): impl이 안 읽는 표면은 시나리오에 넣지 않는다(예: route에 도구 기대 금지).
  기대 자체를 `GET /agents/agent-impls`의 consumes로 자가 검증(스펙 171 drift 가드와 같은 결).

## 설계

### 위치·실행 방식

```
tests/suite/
  run.py         # 러너: 프리플라이트 → 부트스트랩 → 시나리오 실행 → 리포트 (--only KEY 필터)
  fixtures.py    # 멱등 픽스처 부트스트랩 (이름 기준 get-or-update)
  scenarios.py   # 시나리오 매트릭스 = 데이터 선언 (기대 기록 포함)
  _sse.py        # SSE 수집·trace 프레임 파서 (chat.py 계약: 최종 event:trace)
```

- 기존 verify_NNN 패턴 계승: **in-process ASGI**(`httpx.ASGITransport(app=app)`) + principal 우회
  (별도 서버 기동 불요, DB만 필요). 채팅은 SSE 전체를 모아 최종 `event: trace` 프레임에서 단언.
- 실모델 선택: 등록 모델 중 `provider_kind != mock`인 기본 chat/embedding을 자동 탐지,
  `SUITE_CHAT_MODEL`/`SUITE_EMBED_MODEL` 환경변수로 고정 가능.

### 픽스처 (접두사 `suite-`, 멱등 get-or-update)

| 이름 | impl | 연결 | 용도 |
|---|---|---|---|
| suite-direct | (직접) | 도구(echo·web_search·delete_record)+장기 기억+RAG 컬렉션 | 주력 base — 오버라이드 변주의 기준점 |
| suite-direct-bare | (직접) | 없음 (모델만) | 무연결 대조군 |
| suite-ephemeral | (직접) | 도구(비승인만) | 비영속 경계 (스펙 235/237) |
| suite-pipeline | pipeline | 노드 3(검색 노드=RAG 도구, 요약 노드=무도구, 기억 노드=장기 기억) | 노드 소유 표면·노드 오버라이드(287) |
| suite-orchestrate | orchestrate | capabilities=[suite-direct] + 장기 기억 | 위임 기록(brokerCalls) |
| suite-route | route | 장기 기억만 (consumes 정합) | 커스텀 플로우(스킬) 분기 |
| suite-plan-execute | plan_execute | 도구+RAG | 커스텀 플로우(스킬) 계획-실행 |
| suite-artifact | artifact_form | artifactSpec 최소 2슬롯 | 산출물·HIL 표면 (여력 있으면 — P2) |

- **MCP**: seed의 local-tools(실 MCP, echo/web_search/delete_record(승인 필요))와 calc-tools(custom)를
  그대로 쓴다 — 새 MCP 신설 없음(source=custom은 API 생성 봉인, 탐색 #7).
- **RAG**: `suite-kb` 컬렉션 1개를 **실 embedding 모델로** 생성·인제스트. 문서는 고유 토큰이 박힌
  결정적 텍스트 2건(예: "SUITE-FACT-ALPHA: …") — 히트 단언은 이 토큰으로.
- **기억**: suite 전용 유저 스코프에 mem0 기억 2건을 API로 심는다(예: "사용자의 커피 취향은 SUITE-PREF-LATTE").
  회상 단언은 recall_diag `stored>0 && count>0` + 히트 텍스트의 고유 토큰.
- 픽스처는 seed를 건드리지 않는다(learning 045 — seed 결합 금지). suite 픽스처만 소유·갱신.

### 시나리오 매트릭스 (1차 32개)

축 표기: 도구 T(유/무/승인), 기억 M(장기 유/무·단기 깊이), 세션 S(재사용/신규/비영속), 오버라이드 O(적용/대조).

| # | 대상 | 시나리오 | 기록 단언 |
|---|---|---|---|
| 1–4 | suite-direct | 도구 지시("echo로 …") / 도구 없이 질문 / RAG 질문(SUITE-FACT) / 기억 질문(SUITE-PREF) | trace.mcp에 echo 1회 / toolDiag.called=0 / ragCollections+응답에 토큰 / used_memory+토큰 |
| 5–6 | suite-direct | 2턴 세션 재사용(1턴에 숫자 제시→2턴 회수) / historyDepth=0 오버라이드로 같은 실험 | 2턴 응답에 숫자 포함 / 숫자 부재+trace.overrides.historyDepth |
| 7–9 | suite-direct+O | 오버라이드 tools=[]("echo로" 지시) / 오버라이드 memories=[] / 오버라이드 temperature | toolDiag bound=0 / used_memory 없음 / trace.overrides에 temperature |
| 10 | suite-direct | 대조: 저장 설정 그대로(오버라이드 없이) 도구+기억 동시 발동 | mcp+used_memory 동시 존재, trace.overrides 부재 |
| 11–12 | suite-direct | 승인 도구(delete_record) 발동→interrupt / 승인 후 재개 | approval 프레임+Approval 행 생성 / 재개 후 trace에 delete_record 실행 |
| 13–15 | suite-ephemeral | 채팅 1턴 / 승인 도구 시도 / DB 불변 실측 | 응답 정상 / 승인 요구 도구 실행 거부(계약 문구) / Session·Message·checkpoint 행 증가 0 |
| 16–20 | suite-pipeline | 노드별 도구 발동 / 노드 오버라이드로 프롬프트 교체(287) / 노드 오버라이드 tools 제거 / temperature 오버라이드 / 노드 기억 회상 | trace.mcp 노드 도구 / overrides.nodes 반영+효과 / 해당 도구 호출 소멸 / overrides.temperature / used_memory |
| 21–24 | suite-orchestrate | 위임 발동 / 오버라이드 capabilities=[] / 기억 회상 / 위임 결과 종합 | brokerCalls≥1 / brokerCalls 0 / used_memory / 최종 응답 비어있지 않음+trace 종합 |
| 25–26 | suite-route | 분기 A 입력 / 분기 B 입력 | trace(또는 응답 경로 기록)에 해당 분기 흔적 — route 구현의 관측 표면 확인 후 확정 |
| 27–28 | suite-plan-execute | 도구 포함 과제 / RAG 포함 과제 | trace.mcp / ragCollections |
| 29–30 | suite-direct | RAG 오버라이드 vectorTables=[] / 대조(저장 설정 RAG 히트) | ragCollections 부재 / 존재 |
| 31 | 프리플라이트 자체 | mock만 있는 환경 시뮬(단위) | exit 2 + 명확한 메시지 |
| 32 | 픽스처 | 부트스트랩 2회 멱등 | 2회차 생성 0건·개수 불변 |

(#25–26 route의 관측 표면, #루프 artifact(HIL 폼)는 구현 중 실측으로 확정 — 표면이 없으면 스펙에
"관측 불가=OUT" 정직 기록 후 축소. 스킬(agent-flow 플로우) 커버는 route·pipeline·orchestrate·plan_execute 4종.)

### 구현 확정 (실측 — 1차 32 계획 → **최종 30**: artifact 2개는 P2 OUT, 회상 2개 추가)

- 최종 구성: 데이터 시나리오 23(scenarios.py) + 커스텀 7(run.py: 승인 왕복·비영속 DB 불변·비영속 승인
  거부·노드 오버라이드 2종·부트스트랩 멱등·프리플라이트 단위) = **30**. route 분기는 trace 타임라인
  (`graph[].node`)으로 관측 가능 확정. 노드형 회상은 `trace.memoryRecalls`(노드·건수 — 268 P2 프록시)로
  단언(`memory_recall_min`). artifact(HIL 폼) 2개는 P2 OUT 유지.
- **구현 중 실측으로 잡은 계약 4건**(스위트가 첫 실행에서 발견 — 존재 가치 실증):
  1. **히스토리는 클라이언트 계약**: 서버 메인 경로는 세션 대화를 DB에서 재구성하지 않고
     `body.messages` 전체를 `_window(historyDepth)`로 절단한다. 러너는 플레이그라운드처럼 대화를
     누적 전송해야 한다(현재 턴만 보내면 어떤 depth여도 히스토리 0).
  2. **노드형 풀 파생은 폼의 책임**: API로 직접 만든 노드형은 `vectorTables`/`memories` 풀을 함께
     저장해야 한다(폼 derivePipelinePool 미러). 풀이 비면 컬렉션별 rag 도구가 안 빌드돼 노드 도구가
     조용히 미바인딩(learning 151류).
  3. **조율형 위임의 두 게이트**: 위임 대상은 활성 버전 보유(서빙 중, 스펙 256)여야 후보에 뜨고,
     발견은 lexical 랭킹(rank_candidates — 겹침 0 제외)이라 프롬프트에 대상 이름 토큰이 필요하다.
  4. **in-process ASGI는 lifespan 미실행**: HIL 재개에 필요한 durable 체크포인터를 러너가
     `checkpointer.init_checkpointer()`로 직접 초기화해야 한다(안 하면 "resume 불가"로 조용히 무산).

### 설계 대안 검토 (기각 사유)

- **평가 하네스(137~143) 재사용**: assert 어휘·러너가 이미 있으나, 평가 러너는 **오염 제로**(세션
  미영속)가 설계라 세션 재사용·비영속 대조·HIL 승인 왕복 축을 검증할 수 없다. 스위트는 독립 러너로
  가되 assert 어휘(도구 호출 등)는 참조만. 장기적으로 겹치는 케이스는 평가 문제집으로 승격 가능(OUT).
- **browser e2e로 구현**: UI 층은 기존 audit/verify-*.mjs가 소유. 이 스위트는 API 층 조합 검증 —
  더 빠르고 실모델 비용을 UI 렌더에 안 쓴다.

## OUT (이번에 안 함)

- A2A 루프백·외부 에이전트 시나리오(155가 소유), 커스텀 MCP 신설, 응답 품질 평가(평가 하네스 소유),
  cron 상시 실행(백로그 "루프 자동화"와 합류), CI 통합.
- artifact HIL 폼 왕복이 관측 표면 부족으로 축소될 경우 후속 스펙.

## 검증 (이 스펙 자체의)

- 완료 기준 1~5를 그대로 실행해 수치로 확인(멱등 2회·연속 2회 초록·시나리오 수·exit 코드 3종).
- 적대 검증: codex로 "스위트가 초록인데 실제로는 깨져 있을 수 있는 경로"(빈 초록·단언 우회) 리뷰.
