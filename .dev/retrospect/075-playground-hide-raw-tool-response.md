# 075 — 채팅 본문에서 도구(블록) 원본 응답 숨김 (회고)

> 스펙: `docs/spec/092-playground-hide-raw-tool-response.md` (제안 #3)
> 관련: learning 094(본건 도출), learning 089/090(노출 polarity는 *목적*이 정함), spec 086·079(인스펙터 독립 trace).

## 무엇을 했나

Playground에서 에이전트가 도구 블록(메모리/MCP/RAG)을 호출하면 그 **원본 응답(ToolMessage.content)**이
채팅 본문에 새고 뒤에 모델 추론이 이어붙던 문제(#3)를 백엔드 스트림 게이트로 닫았다. `runtime.is_tool_message
(msg) = isinstance(msg, ToolMessage)` 단일 술어를 두고 두 sink(`event_stream`·`stream_local_reply`)가
공유. 프런트 0줄.

## 배운 것 (시간순)

### 1. `.type` 문자열은 청크/비청크 간 불안정 — isinstance로 가야 했다 (verify 단위 런이 codex 전에 잡음)
처음 술어를 `getattr(msg,"type","")=="tool"`로 짰다. probe는 비청크 `ToolMessage.type=="tool"`만 봤기
때문. 그런데 verify_092 단위 런이 **`ToolMessageChunk.type=="ToolMessageChunk"`**(≠"tool"),
`AIMessageChunk.type=="AIMessageChunk"`(≠"ai")를 실측해 실패시켰다 → `.type` 문자열은 *스트리밍 청크에서
바뀐다*. `ToolMessageChunk`는 `ToolMessage` 서브클래스라 `isinstance`가 청크·비청크를 둘 다 잡고 AI는
제외. **검증 사다리 rung①(단위)이 적대 타자(codex) 전에 결함을 잡은 실례** — 사다리 가치 입증.

### 2. 적대 타자(codex)는 "내가 만진 줄"의 *선재* 잠복 버그를 드러낸다 (P1)
codex가 [P1]로 `content`가 str이 아니라 **content-block 리스트**(AIMessageChunk)일 때 `"".join(acc)`가
`try` 밖에서 TypeError → trace/done/persist 전부 죽는다고 짚었다. 이건 092 *이전부터* 같은 줄에 있던
잠복 버그지만, **내가 그 줄을 만지고 정규화기(`_content_text`)가 이미 존재**했으므로 092 하드닝으로 함께
봉합했다(boil-the-ocean: 한계비용 0이면 완전체). 교훈: 적대 리뷰는 "이 변경의 결함"만이 아니라 "이 변경이
밟고 선 코드의 결함"도 표면화한다 — 같은 줄·기존 도구면 함께 고치는 게 정직하고 싸다.

### 3. "관측성 손실 0"은 과장이었다 — 적대 P2가 내 *주장*을 정정 (probe-deeper)
스펙에 "본문서 ToolMessage 걸러도 디버깅 손실 0"이라 적었는데, codex가 [P2]로 **MCP result는 2000자 캡,
RAG는 raw 스니펫이 아니라 건수만** calls_sink에 적재됨을 짚었다. 즉 *전문 원본*은 인스펙터에도 캡/요약된다.
사용자가 raw 숨김을 *명시 요청*했으니 의도된 동작이긴 하나, "손실 0" 단언은 틀렸다 → 배경·주석·스펙을
정정. **내 단정("손실 0")을 측정 가능한 사실(캡/요약)로 내려야 했다** — probe-deeper의 자기주장 버전.

### 4. polarity(blocklist) fail-open은 유지하되 *현실 표면을 측정해* 정당화
codex가 blocklist(isinstance ToolMessage)는 미래 신종 메시지 타입에 fail-open이라 지적(P2). 유지를 택하되
근거를 직감이 아니라 측정으로: 표준 ReAct `messages` 스트림은 model 노드 AIMessage·tools 노드 ToolMessage
**만** 발화한다(Human/System은 입력이라 청크 안 됨 — probe 확인). 신종 누수 표면은 *커스텀 그래프가 새
BaseMessage 서브클래스 발화* 경우로 좁다. allowlist(`=="ai"`)는 커스텀 에이전트 정당 텍스트 과잉차단 →
사용자가 숨길 대상 명시했으므로 blocklist가 의도 충실(089/090 축). 결정 유지 + 표면 명시.

### 5. 빈 어시스턴트 영속은 *이전보다 개선*이라 수용
도구만 부르고 최종텍스트 없는 턴 → 필터 후 `full==""` → 빈 assistant 영속, memory.add 스킵. codex가 P2로
"모델링 안 됨" 지적. 그러나 **092 이전엔 그 자리에 raw가 새어 영속**됐으므로 빈 문자열은 엄선상 개선(누수
제거). ReAct 종단은 보통 비지 않아 도달 드묾. 별도 가드는 파킹(과교정 금지). 정직: 누수 0·빈 턴 무해.

## 검증 사다리 3런 (비겹침) — 실제로 셋이 다른 걸 잡음
- **rung① 단위**: `.type` 문자열 불안정을 codex 전에 잡음(→isinstance). 정규화기 list 처리 단언.
- **rung② 실 그래프 통합**: 실 ReAct 그래프 + scripted 모델로 `event_stream` 필터+정규화 코드경로 재현 —
  RAW 본문·acc 제외, FINAL 보존, **list-content 무크래시**(P1 회귀), calls_sink 보존. 17 passed.
- **rung③ 적대 codex**: P1(content-block 크래시)·P2 polarity·인스펙터 과장·빈 영속·검증 협소 — 단위/통합이
  *상상 못 한* 결함. 셋이 안 겹친다.
- **브라우저(보조)**: `shot-hide-tool-092.mjs` → HIDE092_OK(정상 텍스트 라이브 렌더·raw 덤프 없음). 실
  도구호출 재현은 모델 의존이라 통합 테스트로 대체(한계 명시).

## 다음에 적용
- 스트림 메시지 판별은 **`.type` 문자열 말고 isinstance**(청크 서브클래스 안정). learning 094.
- 스트림 본문에 모델 content를 쌓을 땐 **항상 str 정규화**(content-block 리스트 가정) — `_content_text`.
- 스펙에 "손실 0/완전" 단언을 쓰기 전에 **저장 경로의 캡·요약을 실측**하고 그 한계를 적는다.
