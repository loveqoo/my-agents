# 092 — 채팅 본문에서 도구(블록) 원본 응답 숨김

> 보고(#3): "플레이그라운드에서 메모리·mcp 등 다른 블록을 호출한 뒤 그 응답으로 추론해 대답할 때 응답이
> 이상함. **블록의 원본 응답이 나오고 붙어서 추론 내용이 나오는데, 블록의 원본 응답은 보여주지 않아도 될
> 것 같아. 그럴 가능성을 찾아보자.**"
> 참고 자산: learning 091(렌더시점 휴리스틱·covering-guard·스트림 게이트 — 본건은 *백엔드 스트림 게이트*),
> 089/090(노출 polarity는 *목적*이 정함), spec 086·079(도구 호출은 인스펙터 trace에 독립 적재 → 본문서
> 빼도 관측성 손실 0).

## 배경 — 측정한 현황 (probe로 실측)

- **누수 지점 = 백엔드 스트림 변환부, 메시지 타입을 버림.** `chat.py:656-664` `event_stream()`은
  `graph.astream(..., stream_mode=["messages","updates"])`의 `messages` 청크에서 `msg_chunk`의 **타입을
  검사하지 않고** `getattr(msg_chunk, "content", "")`를 그대로 `{text}` 프레임으로 흘리고 `acc`에도 쌓는다.
  ReAct 그래프(`create_agent`)의 `messages` 모드는 **모델 노드의 `AIMessage`뿐 아니라 tools 노드의
  `ToolMessage`(도구 실행 원본 응답)도** 청크로 낸다 → 원본이 본문에 새고 그 뒤 추론 텍스트가 이어붙는다.
- **실측(`.dev/probe_092_tool_message_stream.py`)**: scripted ReAct 그래프로 확인 — `messages` 모드가
  순서대로 `AIMessage(node=agent, content="")` → **`ToolMessage(node=tools, content=원본)`** →
  `AIMessage(node=agent, content=최종텍스트)`를 흘린다. **ToolMessage는 `msg_chunk.type == "tool"`**,
  모델 텍스트는 `"ai"`. → **`type=="tool"` 게이트가 원본만 정확히 거르고 'ai'는 보존, 거짓양성 0**.
- **`acc` 오염 범위가 표시보다 넓다.** `full = "".join(acc)`(728)는 (1) 어시스턴트 메시지로 **영속**(756),
  (2) **mem0 메모리에 저장**(763-765), (3) **토큰 추정**(731)에 쓰인다. 즉 원본이 `acc`에 들어가면 표시뿐
  아니라 *영속 대화기록·장기 메모리·토큰수*까지 오염된다 → 게이트는 yield와 `acc.append` **둘 다**를 막아야 한다.
- **형제 누수: A2A 서빙 경로도 동일.** `stream_local_reply`(`chat.py:553-556`)도 타입 무검사로 `content`를
  yield한다 — 우리 에이전트가 *외부 A2A 호출에 응답*할 때 도구 원본이 외부 소비자에게 샌다(본문 누수보다
  나쁠 수 있음). covering-guard(learning 091): 보고된 한 곳만 막으면 형제가 샌다 → **두 sink를 같은 술어로**.
- **프런트는 구분 불가(신호 미도착).** `api.ts:486-503`은 `{text}`만 받아 무차별 `onToken`, `Playground.tsx`는
  마지막 ai 버블에 이어붙임. 프레임에 role/type 메타가 없다 → 프런트에서 거르려면 백엔드가 먼저 타입을
  실어야 하므로, **어차피 백엔드 수정 필요**. 그럴 바엔 백엔드에서 바로 거르는 게 최소 변경(프런트 0줄).
- **인스펙터는 독립 경로로 호출 메타 보존.** MCP/RAG 도구 결과는 `runtime.py`의 `calls_sink`(`_wrap_mcp_tool`·
  `build_rag_tool`)에 `{server,tool,status,ms,args,result}`로 적재 → `assemble_trace(mcp_calls=...)` →
  `trace["mcp"]` → `event:trace` 프레임 → Inspector. 본문서 ToolMessage를 걸러도 도구 **args/타이밍/상태 +
  결과요약**은 인스펙터에 남는다. ⚠ 단 "원본 손실 0"은 과장 — 적대 검증(codex P2)이 정정: **MCP result는
  2000자 캡**(`_wrap_mcp_tool`), **RAG는 raw 스니펫이 아니라 건수("N건 반환")만** 적재. 즉 *전문 원본*은
  인스펙터에도 캡/요약된다. 그러나 **본문에서 raw를 숨기는 것이 사용자의 명시 요청**이므로 이는 의도된
  동작이고, 호출 메타(args/타이밍/요약)는 디버깅에 충분(스펙 086·079·087과 정합).

## 결정

- **백엔드 단일 술어로 본문에서 도구 메시지 제외.** `runtime.py`에 순수 술어 `is_tool_message(msg) -> bool`
  (`isinstance(msg, ToolMessage)`)를 두고, **두 sink가 공유**한다(드리프트 0). ⚠ `.type` 문자열로 판별하면
  안 됨 — verify_092가 실측해 잡음: `ToolMessage.type=='tool'`이지만 `ToolMessageChunk.type=='ToolMessageChunk'`,
  `AIMessageChunk.type=='AIMessageChunk'`라 **`type` 문자열은 청크/비청크 간 불안정**. ToolMessageChunk는
  ToolMessage 서브클래스라 isinstance가 둘 다 잡고 AI 메시지(청크 포함)는 제외:
  - `chat.py` `event_stream`(659-664): tool 청크면 yield·`acc.append` **둘 다 스킵**(표시+영속+메모리+토큰 정화).
  - `chat.py` `stream_local_reply`(553-556): tool 청크면 yield 스킵(A2A 서빙 동일 정화).
- **Polarity = blocklist(`=="tool"`), allowlist(`=="ai"`) 아님 (089/090 축).** *목적*은 "어시스턴트의 *말*을
  보여준다"지만, 사용자가 숨길 대상을 **명시("블록의 원본 응답")**했으므로 그 대상을 정확히 지목하는 blocklist가
  의도에 충실하다. allowlist(`=="ai"`만 통과)는 커스텀 에이전트(spec 085/089)가 *정당하게* 흘릴 수 있는
  비-ai·비-tool 텍스트까지 과잉 차단할 위험. 단 blocklist는 미래 신종 메시지 타입 누수에 fail-open이므로
  **이 polarity 선택을 적대 리뷰(③)에 명시적으로 회부**한다(목적이 polarity를 정한다 — learning 090).
- **인스펙터/trace는 무변경.** 도구 호출 관측은 `calls_sink`가 책임 — 본 스펙은 *채팅 본문 sink*만 만진다.
- **프런트 0줄.** 신호를 백엔드에서 소거하므로 `api.ts`·`Playground.tsx`·`DebugChat.tsx` 변경 없음.

## 설계

### 1. 순수 술어 (`packages/api/src/.../runtime.py`)

```python
def is_tool_message(msg) -> bool:
    """도구 노드가 낸 ToolMessage(도구 원본 응답)인가. 채팅 본문 sink에서 제외하는 단일 판정.
    isinstance — .type 문자열은 청크/비청크 간 불안정(verify_092 실측). ToolMessageChunk는 서브클래스."""
    return isinstance(msg, ToolMessage)
```

### 2. 두 sink 게이트 (`chat.py`)

```python
# event_stream (messages 분기)
if stream_mode == "messages":
    msg_chunk, _meta = chunk
    if runtime.is_tool_message(msg_chunk):   # 도구 원본 응답 — 본문/영속/메모리서 제외
        continue
    text = runtime._content_text(getattr(msg_chunk, "content", ""))  # content-block 리스트 → str(092 codex P1)
    if text:
        acc.append(text)
        yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"

# stream_local_reply (A2A 서빙)
async for msg_chunk, _meta in graph.astream(...):
    if runtime.is_tool_message(msg_chunk):
        continue
    text = runtime._content_text(getattr(msg_chunk, "content", ""))
    if text:
        yield text
```

### 3. content 정규화 (codex P1 — 선재 잠복 크래시 동시 봉합)

`AIMessageChunk.content`는 str이 아니라 content-block 리스트(`[{'type':'text','text':...}]`)일 수
있다(Anthropic 등). 도구 필터와 무관하게 두 sink가 `getattr(content)`를 그대로 `acc.append` →
`"".join(acc)`로 합치므로 list가 섞이면 **`try` 밖에서 TypeError**가 나 trace/done/persist가 통째로
죽는다. 이는 092 *이전부터* 같은 줄에 있던 잠복 버그지만, 내가 그 줄을 만지고 `runtime._content_text`
정규화기가 *이미 존재*하므로(`_wrap_mcp_tool`이 도구 반환에 쓰던 것) 092 하드닝으로 함께 봉합한다 —
두 sink 모두 `_content_text(getattr(...))`로 str을 보장. resume_approval(914)은 `type=="ai"`만
추출하는 별 경로라 본 스펙 비대상(도구 누수 아님).

## 검증 사다리 3런 (비겹침)

- ① **단위 시맨틱**: `tests/verify_092_tool_chunk_filter.py`(`uv run python`) — 순수 술어 `is_tool_message`를
  ToolMessage·ToolMessageChunk·AIMessage·AIMessageChunk·HumanMessage·`content=""` 등에 대해 직접 검증
  (tool만 True). 술어 단독 의미.
- ② **실 그래프 통합**: 같은 테스트가 **실제 ReAct 그래프**(`create_agent`/`build_agent` + 실 `StructuredTool`
  + scripted 모델)를 `stream_mode="messages"`로 돌려 `event_stream`과 *동일한 필터 코드경로*를 적용 →
  RAW가 yield 프레임·`acc` 양쪽에서 빠지고 FINAL은 남는지, 그리고 **병렬 `calls_sink` 캡처엔 도구 결과가
  여전히 있는지**(관측성 보존) 단언. 술어가 아니라 *전체 흐름*을 본다(probe_092를 어설션으로 승격).
- ③ **적대 타자(codex)**: "보장 목록의 여집합" — **polarity(blocklist vs allowlist) 정당성**, 빈 content 처리,
  ToolMessageChunk(스트리밍 분할) type 보존, 도구만 호출하고 최종텍스트 없는 턴서 본문 빈 경우, A2A sink
  누락 여부, `acc` 정화가 memory/persist/token에 미치는 의도치 않은 영향(예: 도구만 부른 턴 memory 미저장).
- 브라우저(보조): 일반 텍스트 응답이 회귀 없이 렌더되는지 Playground에서 확인(도구 실호출 재현은 실모델
  의존이라, 재현 가능하면 도구 원본 미표시까지 캡처·불가하면 무회귀만 확인하고 한계 명시).

## 적대 검증 결과 (codex challenge, rung ③)

codex가 P1 1건 + P2 4건. 맹신 않고 코드로 재확인 후 처리:

- **[P1] content-block list 크래시 → 수정.** 위 §3. 선재 잠복이나 같은 줄·정규화기 기존재 →
  두 sink를 `_content_text`로 봉합. verify_092에 회귀 5건 추가(unit 정규화 3 + 통합 list-content 2).
- **[P2] polarity fail-open → 결정 유지(현실 표면 협소).** blocklist는 미래 신종 타입에 fail-open이나,
  표준 ReAct `messages` 스트림은 **model 노드 AIMessage·tools 노드 ToolMessage만** 발화한다(Human/System은
  *입력*이라 청크로 안 나옴 — probe 확인). 신종 누수 표면은 *커스텀 그래프가 새 BaseMessage 서브클래스를
  발화*하는 경우로 좁다. allowlist(`=="ai"`)는 커스텀 에이전트의 정당한 비-ai 텍스트를 과잉차단 →
  사용자가 *숨길 대상을 명시*했으므로 blocklist가 의도 충실(089/090 축). 결정 유지, 표면을 명시.
- **[P2] 도구만 부른 턴 빈 어시스턴트 영속 → 수용.** 필터 후 `full==""`면 `_persist`가 빈 assistant
  메시지를 쓰고 `memory.add`는 `full` falsy로 스킵. *092 이전엔 그 자리에 raw가 새어 들어가 영속*됐으므로
  빈 문자열이 **엄선상 개선**(누수 제거). ReAct 종단은 보통 비지 않는 최종 AIMessage라 도달 드묾. 별도
  가드는 후속 후보로 파킹(과교정 금지) — 현 동작은 정직(누수 0, 빈 턴은 무해).
- **[P2] 인스펙터 "손실 0" 과장 → 정정.** 배경/주석 정정(MCP 2000자 캡·RAG 건수만). 본문 raw 숨김이
  사용자 요청이므로 의도된 동작; 호출 메타는 디버깅에 충분.
- **[P2] 검증 협소 → 보강.** verify_092가 실 게이트 코드경로를 재현하되 list-content·정규화 케이스 추가.
- **covering 확인**: resume_approval은 `type=="ai"`만 추출(도구 누수 아님), remote A2A는 무타입 텍스트
  패스스루(술어 무관). 추가 raw ToolMessage sink 없음 — 두 sink가 닫힌 집합.

## 완료 기준 (측정 가능)

- [x] `runtime.is_tool_message` 순수 술어 + 두 sink(`event_stream`·`stream_local_reply`) 공유 게이트.
- [x] content-block 정규화(`_content_text`)로 두 sink list-content 크래시 봉합(codex P1).
- [x] `verify_092` GREEN(17 passed): 술어 단위 + 정규화 단위 + 실 그래프 통합(RAW 본문·acc 제외, FINAL
  보존, list-content 무크래시, calls_sink 보존).
- [x] 적대 codex 회부 완료 — P1 수정, P2 4건 처리(수정/정정/수용+근거 명시). 미해결 P1 없음.
- [x] admin 무회귀(프런트 0줄), 브라우저 일반 응답 렌더 무회귀(`shot-hide-tool-092.mjs` → `HIDE092_OK`,
  Doc Translator 응답 정상 렌더·raw 덤프 없음·스트림 회귀 에러 0).

## 비목표

- 도구 호출을 "칩/마커"로 구조화 표시(거르지 않고 보여주기) — 사용자는 *숨김*을 원했고 인스펙터가 이미
  full을 보유. 후속 후보로 파킹(과한 금칠 금지).
- 프런트 프레임에 type 메타 추가·렌더 분기. 인스펙터 trace 스키마 변경. 도구 호출 자체 비활성화.
