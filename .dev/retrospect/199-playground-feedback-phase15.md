# 199 — 플레이그라운드 피드백(스펙 209 Phase 1.5): "민감 배관"이 실은 트레이스 프레임 옆 한 줄씩

## 맥락
Phase 1(세션 뷰 피드백)·Phase 2(수확) 후, 사용자가 Phase 1.5(플레이그라운드 응답에도 👍/👎)를 선택.
회고 197이 "message-id 배관이 스트리밍 영속 경로 5곳을 건드려 위험"이라 분리했던 그 조각.

## "5곳 민감 배관"이 생각보다 작았다
분리 사유는 "_persist 호출부 5곳이 민감한 스트리밍 영속 경로"였다. 열어 보니 5곳 중 **4곳이 동일 패턴**
(`_persist`→`yield trace`→`yield done`)이라, `_persist`가 id를 반환하게 하고 각 곳에 `yield _mid_frame(mid)`
한 줄씩 = 4줄. 5번째(resume_approval)는 **비제너레이터**(-> None, 승인 재개는 out-of-band)라 스트림이
없어 프레임 방출 불가 → 재개 턴 피드백은 **Phase 1의 세션 리로드 경로**(GET /messages가 이미 id+feedback
반환)로 자연히 처리. 즉 "5곳"이 실제론 "4곳 한 줄 + 1곳 무변경(다른 경로가 이미 커버)"이었다.
교훈: **"민감·광범위해 보임"을 실측 전에 위험 상수로 쓰지 말 것**([[probe-deeper-before-concluding]]의
확장 — 이번엔 위험을 *과대*평가). 분리 자체는 옳았지만(Phase 1 먼저 완성), 크기는 열어봐야 안다.

## 배관보다 프론트 타입 블록이 함정
가장 시간을 먹은 건 백엔드가 아니라 **DebugChat.tsx의 중복 타입 블록**. `interface DebugChatProps`(별도)
와 `ChatHeader`의 인라인 타입이 둘 다 `onReloadSessions`·`currentSessionId`를 갖고 있어, prop을 엉뚱한
함수(ChatHeader)에 넣었다 tsc가 "declared but never read"+"cannot find name"로 잡음. 같은 필드명이 여러
컴포넌트에 흩어지면 **어느 함수의 타입인지 tsc 에러 라인으로 역추적**해야 한다(grep로 `export function`
위치 대조). 실제 렌더(FeedbackButtons)가 있는 함수(=`export function DebugChat`, DebugChatProps 사용)에
넣어야 했다.

## 설계 메모 (재사용의 복리)
- FeedbackButtons는 Phase 1에서 세션 뷰용으로 만든 걸 **그대로** 재사용(sessionId+messageId+value+onChange).
  플그는 currentSessionId를 이미 프롭으로 갖고 있어 배선만.
- Phase 1의 GET /messages(id+feedback)를 loadSession 매핑에서 재사용 → 과거 세션 복원 시에도 피드백 표면
  +resume 턴 피드백까지 공짜로. **입구 하나 잘 만들면(Phase 1) 뒤 Phase가 그 위에 싼다.**
- 플그 피드백이 영속되면 그대로 Phase 2 수확 대상 → **세 Phase가 한 파이프라인으로 닫힘**.

## 다음에 적용
- 위험 격리로 분리한 조각은, 착수 시 **크기를 재측정**(과대평가 흔함). 분리 판단과 크기 추정은 별개.
- 프론트 prop 추가 전 **그 렌더가 어느 함수 스코프인지 먼저 확정**(중복 타입 블록 주의). tsc 에러의
  파일:라인으로 함수 역추적.
- 스트림에 새 프레임을 넣을 땐 **비스트리밍 경로(out-of-band)는 다른 표면(리로드)이 커버하는지** 확인 —
  모든 호출부에 억지로 넣지 말 것.
