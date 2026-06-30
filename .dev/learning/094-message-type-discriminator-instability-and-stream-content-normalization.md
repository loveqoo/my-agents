# 094 — 스트림 메시지 판별은 `.type` 문자열 말고 isinstance / 본문에 쌓는 content는 항상 str 정규화

> 도출: 스펙 092(채팅 본문서 도구 원본 숨김) + 회고 075. 관련 [[probe-deeper-before-concluding]],
> learning 089/090(노출 polarity는 목적이 정함), learning 091(covering-guard·스트림 게이트).

## 결론 (두 결합 교훈)

LangGraph `stream_mode="messages"` 스트림에서 메시지 종류로 분기할 때:

### A. 판별자는 `.type` 문자열이 아니라 `isinstance` — 청크에서 문자열이 바뀐다
- 비청크: `ToolMessage.type=="tool"`, `AIMessage.type=="ai"`.
- **청크: `ToolMessageChunk.type=="ToolMessageChunk"`, `AIMessageChunk.type=="AIMessageChunk"`** —
  `"tool"`/`"ai"`가 아니다. 즉 `.type` 문자열은 **청크/비청크 간 불안정**.
- `ToolMessageChunk`는 `ToolMessage`의 서브클래스 → `isinstance(msg, ToolMessage)`가 청크·비청크를
  **둘 다** 잡고 AI 메시지(청크 포함)는 제외. 안정적 술어.
- **measure, don't assume**: probe가 비청크만 봐서 처음엔 `=="tool"`로 짰다. **검증 사다리 rung①(단위)**이
  ToolMessageChunk를 실측해 적대 타자(codex) *전에* 잡았다 — 사다리 단위 런의 값.

### B. 본문 sink에 모델 content를 쌓을 땐 항상 str 정규화 — content는 리스트일 수 있다
- `AIMessageChunk.content`는 str이 아니라 **content-block 리스트**(`[{'type':'text','text':...}]`)일 수
  있다(Anthropic 등). 도구 필터와 **무관한** 별개 표면.
- sink가 `acc.append(content)` 후 `"".join(acc)`로 합치면, 리스트가 섞이는 순간 **`try` 밖에서
  TypeError** → trace/done/persist가 통째로 죽는다. `if content:`는 빈 리스트만 거를 뿐 비지 않은
  리스트는 통과시켜 더 위험(happy-path 초록).
- 정규화기 한 곳(`_content_text`: str→그대로, list→텍스트블록 결합, None→"")를 **도구 반환과 본문
  content가 공유**. 도구용으로 이미 있던 걸 본문 sink가 재사용 = DRY·드리프트 0.

## 왜 (메타)
- 둘 다 뿌리는 "**스트리밍은 비청크 happy-path와 타입/모양이 다르다**". 단발 probe·비청크 단언은 *정착된*
  메시지만 본다. 청크 경로는 (a) 판별자 문자열을 바꾸고 (b) content를 리스트로 쪼갠다. 둘 다 정상 턴
  스크린샷·happy-path 테스트에 **안 보이는 구멍**.
- 선재 잠복(B)은 내가 그 줄을 만지며 표면화됐다. **적대 리뷰는 "변경의 결함"만이 아니라 "변경이 밟은
  코드의 결함"도 드러낸다** — 같은 줄·기존 정규화기면 함께 봉합(boil-the-ocean, 한계비용 0).

## 어떻게 적용
- 스트림 메시지 분기는 **`isinstance(서브클래스 포함)`**. `.type` 문자열 비교 금지(청크 불안정).
- 스트림 본문/영속에 모델 content를 누적하면 **반드시 str 정규화**(content-block 리스트 가정). 빈 검사
  (`if content:`)는 리스트 비지 않음을 보장 못 함.
- 검증 사다리 rung①(단위)에 **청크 클래스**(`*MessageChunk`)와 **list content**를 명시적 케이스로 넣어라 —
  비청크·str만 단언하면 스트리밍 구멍이 그대로 남는다.
- 스펙에 "관측성/손실 0" 단언 전, **저장 경로 캡·요약을 실측**하고 한계를 적어라(인스펙터 MCP 2000자 캡·
  RAG 건수만 — codex P2 정정). [[probe-deeper-before-concluding]]의 자기주장 버전.
