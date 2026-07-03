# 155 — 플레이그라운드 A2A 루프백 테스트 (실사용 #8)

## 요구 (사용자)
"playground 에서 우리가 A2A로 오픈한 에이전트를 A2A로 테스트할 수 있어야 한다. 즉, 내부에서
만든 에이전트는 **직접 테스트**하는 방법과 **A2A를 거쳐서** 테스트하는 두 가지 방법이 가능해야 한다."

## 배경 (실측)
- 직접 경로 `POST /agents/{id}/chat`(streamChat): 히스토리 배열 + sessionId + 오버라이드(025) + trace
  이벤트. SSE 프레임 `data:{text}` / `event:trace` / `{session}`.
- A2A 서빙 경로 `POST /agents/{id}/a2a`(154·061): JSON-RPC `message/stream`. 프레임
  `data:{jsonrpc,id,result:{kind:"status-update",taskId,status:{state,message:{parts:[{text}]}}},final}`
  → `data:[DONE]`. **단발 메시지 텍스트만**(`_a2a_user_text`), 세션/히스토리/trace/오버라이드 미전달.
  ui=`stream_local_reply(agent.id, user_text)` 직접 실행, code=1홉 중계(154).
- 노출 게이트(154): source∈{ui,code} + exposed.a2a. external은 봉인(152).

## 설계
### A. 클라이언트 A2A 전송 (api.ts)
- 신규 `streamChatA2A(agentId, text, cb, signal)` — `POST /agents/{id}/a2a`에 JSON-RPC
  `message/stream` 바디(`params.message.parts=[{kind:"text",text}]`) 전송, `credentials:'include'`
  + authHeaders(직접 경로와 동일 인증 — current_principal 쿠키/머신). SSE 프레임을 파싱해
  `result.status.message.parts[].text`를 델타로 `cb.onToken`, `final:true` 또는 `[DONE]`에서 종료,
  `error` 프레임은 `[오류] ...`로 표면화. **세션/오버라이드/trace 없음**(A2A 서빙이 안 넘김 — 정직).
- 스트림 파서는 direct용 `handleFrame`과 프레임 형태가 달라 **별도 함수**(혼용 금지).

### B. 플레이그라운드 모드 토글 (DebugChat + Playground)
- 노출 에이전트(source∈{ui,code} && exposed.a2a)에 한해 헤더에 **Segmented "직접 / A2A"** 표시.
  기본 = **직접**(무회귀 — 기존 send 그대로). 에이전트별 상태(activeId 키)로 유지.
- 미노출/external 에이전트엔 토글 미표시(직접만). 토글 상태는 Playground가 소유(`a2aMode[id]`),
  DebugChat엔 `a2aMode`/`onToggleMode`/`a2aEligible` prop 전달.
- `send()` 분기: A2A 모드 && eligible → `streamChatA2A(id, text, {onToken}, signal)` (마지막 텍스트만,
  단발). 아니면 기존 `streamChat`. A2A 모드에선 인스펙터 trace/세션 피커/오버라이드는 **비활성 안내**
  (A2A 경로가 안 주는 것 — 정직 경계).

### C. 낡은 게이트 정직화 (154 후속)
- `ExposeBadges`(DebugChat:133)·picker 태그(DebugChat:317)의 A2A 배지 게이트가 `source==='ui'`만
  봐서 **154가 허용한 code 노출 에이전트를 놓친다**. `source∈{ui,code}`로 넓혀 배지·토글 노출 일치.

## 정직 경계 (codex 반영 2026-07-03)
- **A2A 테스트는 단발·비영속**: 우리 A2A 서빙이 `stream_local_reply(agent.id, user_text)`로 세션/
  히스토리를 안 넘기므로(멀티턴 contextId 미구현), A2A 모드는 매 턴 독립. **codex Med**: 기존 세션에
  섞으면 "이어 쓴 것"처럼 보이나 DB에 안 남아 재로드 시 사라짐 → **인라인 배너로 정직화**(툴팁만으론
  부족) — "A2A 경유 — 단발 호출(세션·히스토리·trace 미저장·이 턴은 저장 안 됨)".
- **A2A 모드엔 trace 없음**: A2A 프레임에 우리 내부 trace 이벤트가 없어 인스펙터가 빈다. **codex Low**:
  A2A 전송 후 인스펙터가 직전 direct 턴 trace를 stale 표시 → **선택 턴을 새 A2A 턴으로 이동**해 빈
  상태를 보이게(Fix B).
- **code A2A 테스트는 실제 원격 중계**: source=code면 등록 토큰으로 원격을 대리 호출(154 경계 그대로).
- **스트림 엔드포인트의 평문 에러 바디**: message/stream 경로도 dispatch 전 에러(루프가드 -32000·
  미지원 메서드)는 평문 JSON-RPC로 반환 → 클라 파서가 `data:` 없는 프레임을 통째 JSON으로 접음(V3 핀).

## 완료 조건 / 검증 (2026-07-03 완료)
- verify_155 6/6: (V1) 노출 ui message/stream 델타 수신+final+[DONE], (V2) code 노출 스트림 중계,
  (V3) 루프가드 -32000(평문 에러 바디 파싱), (V4) 미노출/부재 404 게이트. ASGI 호출로 서빙 실측.
- e2e 4/4: 노출("Research Assistant") 피커→"직접/A2A" 토글 표시→A2A 선택→"A2A 루프백 스모크"
  전송→A2A 경유 응답 렌더. 미노출("Personal Secretary")은 토글 부재. 앱 상태 사전/사후 curl 불변 확인.
- codex High 0. 경계 2건(Med 세션 혼입·Low trace stale) 정직화 반영. 인증 누락/external 우회/조기
  return의 finally 스킵/AbortError 오렌더 없음(확인).

## OUT
- A2A 멀티턴(contextId 세션 스레딩) — 서빙 확장(#7 근처)에서. 여기선 단발 정직 표기.
- A2A 모드 trace 재구성. 카드 표시(버전/org) 폴리시 — 코어는 JSON-RPC 실행.
