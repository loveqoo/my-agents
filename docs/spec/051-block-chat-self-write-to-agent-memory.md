# 051 — 채팅 자가기록 차단: agent_id 메모리는 어드민 저작 전용

## 배경 / 문제

메모리 테스트 중 로직 오류 발견. 사용자가 채팅에서 *"내 이름은 구남이야. 잘 기억해"*라고 하자,
에이전트가 그 사실을 **agent_id 스코프(에이전트 전용·교차사용자)**에 저장했다. 이름은 **사용자
메모리(user_id)**에 들어가야 하는데, 교차사용자 채널로 샜다.

- DB 확인(`mem0_memories`): 누출 행 `0a6a05d1-17b1-4591-b1c0-e877c2c6d993`
  (`data: "사용자의 이름은 구남이다.", agent_id: "agt_sec_9d4417"`, user_id 없음).
  정상 행 `91e1b821…`(`User's name is Gu Nam`, user_id·run_id)도 **동시에** 존재 — 즉 한 턴이
  두 군데 쓰였다. 사용자 메모리 자동저장(add_scope=user_id+run_id, infer=True)은 **이미 정상 동작**.
- 근본 원인: 채팅 인-챗 자가기록 도구 `save_agent_knowledge`(`runtime.build_agent_memory_tool`).
  agent_id-only·infer=False로 저장. 도구 *설명*에 "유저 개인정보 금지"를 적어 LLM을 규율하려 했으나
  LLM이 이를 어기고 유저 개인사실을 저장(learning 031 "도구 프롬프트 ≠ 격리"의 재현).
- 회상 메커니즘(`mem0_backend.search`)은 축별 단일필터 검색 후 합집합 → **agent_id로 태깅된 건 어떤
  유저에게나 회상된다**(교차사용자가 구조적). 즉 채팅 자가기록은 한 유저의 사실을 전 유저에게 누출.

## 결정 (사용자 지시, 2026-06-28)

처음엔 "agent 전용 메모리 기능 제거(페르소나로 대체)"로 합의했다가 **취소**. 최종 방향:

> **어드민이 수정할 수 있도록 하고, 유저가 채팅에서 넣을 수 없도록 한다. 이는 페르소나 보호에도 도움.**

즉 agent_id 메모리는 **어드민 저작 전용**으로 남긴다. 채팅 LLM의 **자가기록 경로만 차단**한다.
이것이 학습 031/030의 원칙("교차사용자 쓰기는 LLM에 맡기지 말고 인간 게이트")과 정합한다 —
어드민 큐레이션(스펙 029)은 그 인간 게이트 자체이므로 유지가 맞다.

## 범위

### 제거 (채팅 자가기록 경로만)
1. `packages/api/src/api/runtime.py` — `build_agent_memory_tool()` 함수 삭제(`StructuredTool` `save_agent_knowledge`).
2. `packages/api/src/api/chat.py:499-503` — 일반 채팅 경로의 도구 주입 삭제.
3. `packages/api/src/api/chat.py:699-702` — resume(승인 재개) 경로의 도구 주입 삭제.
4. `chat.py:480-485` 주석에서 `save_agent_knowledge 도구·` 표현 정정 → "관리자 저작으로만".

### 유지 (어드민 저작 + 회상)
- `recall_scope`의 `agent_id` 축(chat.py:487, 687) — 어드민 저작 지식을 채팅이 회상하도록 **유지**.
- `agents.py` agent_id 메모리 CRUD 4 라우트(`list/add/update/delete_agent_memory`, `_assert_owns`,
  `_agent_mem_cfg`, `AgentMemoryIn`) — **유지**(어드민 수정 경로).
- `admin/src/api.ts`의 `AgentMemory` + 4 함수, `AgentMemoryPanel.tsx`, `AgentsView.tsx` 사용 — **유지**.

### 정리 / 문구
5. 누출 행 `0a6a05d1-17b1-4591-b1c0-e877c2c6d993` 삭제(유저 개인사실이 교차사용자 스코프에 누출됨).
   정상 user_id 행 `91e1b821…`은 보존(이름은 거기 남아야 함).
6. `AgentMemoryPanel.tsx` 안내문 "에이전트가 스스로 기록한(또는 관리자가 저작한)" → 자가기록이
   사라졌으므로 "관리자가 저작한"으로 정정. 컴포넌트 상단 주석도 동일 정정.

## 검증 (완료 조건)
- [ ] `grep -rn save_agent_knowledge\|build_agent_memory_tool packages/api/src` → 0건.
- [ ] 채팅에서 "내 이름은 …" 류 발화 후 `mem0_memories`에 **agent_id-only 신규 행이 생기지 않음**
      (user_id 행만 생김). 적대적 발화("이걸 너 자신한테 기억해")로도 agent_id 행 미발생.
- [ ] 어드민 패널에서 add/edit/delete가 그대로 동작(agent_id CRUD 유지) + 그 저작 지식이 채팅에서
      회상됨(recall_scope agent_id 유지 확인).
- [ ] 누출 행 삭제 확인(`SELECT … WHERE id='0a6a05d1…'` → 0행), 정상 user_id 행 보존 확인.
- [ ] 타자 검증: 서브에이전트/codex로 "자가기록 경로가 완전히 끊겼고 어드민 경로·회상은 무손상"을
      적대적으로 확인(잔존 주입 지점·테스트 픽스처 누락 점검).

## 비채택 / 메모
- **전체 제거**(어드민 큐레이션까지)는 취소됨 — 어드민 수정 유지가 페르소나 보호와 양립.
- agent_id 메모리는 여전히 교차사용자 회상이다 — 어드민이 **유저 개인정보를 거기 두지 않을** 책임은
  남는다(패널 안내문이 경고). 이 책임을 LLM이 아닌 인간에게 둔 게 이번 결정의 핵심.
