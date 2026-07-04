# 144 — 승인(HIL)을 결정적으로 띄우는 법 (Mock LLM 가능)

## 결론
승인을 **확실히·결정적으로** 띄우는 경로 = **조율형(impl=orchestrate) 에이전트 + capability
`memwrite:user` 하나**. admin/superuser 로그인 필수. 플레이그라운드에서 아무 문장이나 보내면 발화
(예 "내 생일 3월 3일 기억해줘"). Mock LLM으로도 뜬다 — **승인 게이트가 LLM synthesize *이전*의
브로커 delegate에서 터지고, 능력 선택(discover→select)이 순수함수(결정적)이기 때문**.

## 정정 (중요 — "조율형만 승인 가능"은 틀림)
- **직접 응답(DefaultUiAgent)도 승인을 낼 수 있다.** `build_mcp_tools`가 *직접 응답 경로에서도*
  (chat.py:669) MCP 도구에 `_APPROVAL_ACTIONS` interrupt를 씌운다(runtime.py:86-124). 즉 승인은
  **조율형 전유물이 아니다.** 두 경로가 있을 뿐: (1) **그래프-tools** — 모든 에이전트, MCP 도구 호출 시,
  (2) **브로커** — 조율형만, memwrite/memedit/A2A.
- **데모가 조율형으로만 된 진짜 이유 = Mock LLM.** ReAct의 도구-승인은 LLM이 도구를 *호출*해야 뜨는데
  Mock은 tool_call을 안 낸다(mock_remote.py:69) → 안 뜸. 반면 브로커 memwrite는 능력선택이 결정적이라
  Mock으로도 뜬다. 그래서 "결정적 데모"만 조율형이었을 뿐, 능력의 한계가 아니다.

## 왜 지금까지 안 보였나 (핵심 함정)
- 시드 research-assistant(직접 응답)에게 "기억해줘"는 안 뜬다: memory-write는 ReAct 도구셋에 없고(스펙 051),
  memwrite 브로커 능력은 조율형만. delete_record(그래프-tools)는 있지만 Mock이 호출을 안 함.

## Q2 — 승인 후 재개는 실시간 아님 (기술부채 §7)
`resume_approval`(chat.py:1053)은 승인 시 그래프를 **서버사이드로 끝까지 돌려 결과만 원 세션에 영속**한다
("라이브 스트리밍은 빚"). 클라는 폴링도 라이브 스트림도 아니고, 플레이그라운드가 그 세션으로 **복귀할 때
refetch**(DebugChat.tsx:382·Playground.tsx:104, focus/visibility)해 결과를 보여준다. → "승인 후 바로 이어서
대화" UX는 미구현(라이브 resume 스트리밍이 개선 지점).
- **Mock LLM은 tool_call을 방출하지 않는다**(평문만, mock_remote.py:69) → LLM 판단 의존 경로
  (ReAct의 `delete_record` tool-call)는 Mock에서 **발화 불가**. 실 tool-calling 모델도 이 호스트엔 없음
  (:8045=임베딩). 그래서 "도구 호출"류 데모는 결정적이지 않다.
- `memories`(장기 기억 mem0)는 **읽기 회상 주입**일 뿐 memwrite가 아니다. memwrite는 오직
  `config.capabilities`에 `memwrite:user`가 있어야 브로커 allowlist에 들어간다(chat.py:167, broker.py:783).
- 브로커 RBAC: **member는 memwrite를 discover조차 못 함**(broker.py:1038) → 승인이 생성조차 안 됨.
  admin/superuser만. (member의 `memory.write self_approve`는 승인 *해소* 게이트지 invoke 게이트 아님.)

## 재현(UI)
1. 에이전트 → 생성 → **종류=조율형** → capability **"사용자 기억에 저장 · 승인 필요"**(=memwrite:user)
   하나만 체크 → 저장. (모델 Mock 그대로 OK.)
2. 플레이그라운드 → 그 에이전트 → "…기억해줘" 전송 → **⏸ 승인 대기: memory.write** 표면.
3. **승인** 메뉴 → 인자(저장될 내용) 확인 → **승인 및 재개** → 그래프 체크포인트서 재개.
   (mem0 백엔드 없어도 승인은 뜸 — 승인은 저장 *이전* 게이트; 승인 후 invoke가 graceful 실패할 뿐.)

## 데모 자산
- 시드 아님: 세션 중 `approval-demo`(agt_0574b7, 조율형, memwrite:user) 에이전트를 만들어 실증(DB에 잔존,
  Gunam 실습용으로 유지). 승인 큐 화면·인자 노출·재개 모두 스크린샷 검증.
- 참고: 스펙 046이 delete_record를 지운 게 아니다(카탈로그 잔존, mock_mcp.py:24) — Mock이 안 부를 뿐.

## 다음 (Gunam 보안 포인트)
"도구에 승인을 쉽게 설정할 수 있어야 보안이 튼튼" — **도구(MCP) 승인은 지금 `_APPROVAL_ACTIONS`
코드 한 곳에 하드코딩(딱 delete_record 1개)**. 도구별 "승인 필요" 토글로 빼는 게 그 요구의 실체.
[[installed-guard-isnt-covering-guard]]와 결이 같음(설정 가능해야 커버 범위가 는다).

[approval-hil-trigger,orchestrate-plus-memwrite-deterministic,defaultuiagent-no-broker,mock-llm-no-toolcall,per-tool-approval-hardcoded]
