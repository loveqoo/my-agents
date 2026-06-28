# 055 — Playground 세션 이어가기(과거 세션 선택·재개)

## 배경 / 문제
Playground에서 `delete_record` 같은 위험 도구를 호출하면 HIL 승인 요청(스펙 041)이 생성되고
그래프가 멈춘다. 사용자가 **승인 뷰로 이동해 승인하고 돌아오면 Playground가 초기화**된다 —
대화·세션 상태(`convos`/`sessions`)가 `Playground.tsx`의 React 메모리에만 있어 언마운트 시 소실되기
때문이다. 결과적으로 승인된 턴의 최종 답변도 못 보고, 이어서 대화할 수도 없다.

## 진단(코드 확인 완료)
백엔드는 이미 영속·재개를 지원한다 — **빠진 건 불러오는 UI**다.
- interrupt 시: 메시지는 미영속이나 **세션 행 + Approval은 커밋**(`chat.py:_create_approval`,
  `_resolve_session_for_persist` — 스펙 049 lazy-create 위에서 승인 도달 턴은 행 보장).
- 승인 시: `resume_approval`이 체크포인트에서 user/assistant를 추출해 **원 세션(session_id)에
  `_persist`로 영속**(`chat.py:746`). 같은 session_id로 세션을 찾으므로 새 행 안 만듦.
- 조회: `GET /sessions/{id}/messages`(role·content·trace) 존재 + api.ts `getSessionMessages` 배선됨.
- 이어가기: chat 요청에 `session_id`를 넘기면 서버가 agent 스코프로 세션을 재사용하고
  컨텍스트는 **클라이언트가 보낸 `body.messages`를 윈도잉**한다(`_load_context:211-225`,
  `chat.py:531` thread_id = `{ext_agent}:{session_id}:{rand}`). → 과거 메시지를 클라가 다시
  보내면 컨텍스트가 복원되고, 같은 session_id로 계속 같은 세션 행에 쌓인다.

## 빠진 것(이번 범위)
1. **백엔드**: `GET /sessions`에 옵션 `agent_id` 필터 부재 → 활성 에이전트 세션만 추리기 어려움.
2. **프론트**: 세션 피커 + 과거 세션 메시지 로드 흐름 부재.

## 비범위(명시)
- 승인 결과의 **라이브 스트리밍 재연결**(승인하는 순간 Playground로 토큰이 흐르게)은 빚(041 §7)
  으로 유지. 본 스펙은 "**돌아와서 골라 이어가기**"(폴링/수동 선택)만 — 사용자 요구의 직역.
- 대화 상태를 localStorage 등으로 자동 복원하는 것은 비범위(피커로 충분, 단순 유지).
- code/external 소스 에이전트의 세션 재개는 비범위(로컬 그래프 아님 — 기존대로).

## 설계

### A. 백엔드 — `GET /sessions` agent 필터 (작게)
- `list_sessions`에 `agent_id: str | None = None` 쿼리 파라미터 추가.
- 주어지면 `Agent.agent_id == agent_id`인 agent의 `pk`로 `Session.agent_pk` 필터(서브쿼리 또는
  사전 조회). 미지의 id면 빈 결과(관대, 404 아님 — 목록 API 일관성).
- `counts`(배지 집계)는 **필터 무관 전역 유지**(스펙 034 의미 보존) — agent 필터는 `items`/`total`에만.
  (Playground는 counts를 안 쓰므로 영향 없음.)
- `MessageOut`은 그대로 사용(추가 없음).

### B. 프론트 — Playground 세션 피커 + 로드
> 확정(사용자): 피커는 **DebugChat 헤더의 에이전트 피커 옆**에 둔다. 복귀 동작은 **수동 선택만**
> (자동 복원 비범위).

`Playground.tsx`:
- DebugChat 헤더의 에이전트 피커 옆에 **"세션" 선택 컨트롤** 추가. 활성 에이전트
  전환·마운트 시 `listSessions({ agent_id: activeAgent.agentId, limit: 20 })`로 최근 세션 로드.
  - 각 항목 표시: session_id 축약 + 턴 수 + 상태 배지 + 최근 활동시각. 현재 활성 세션 표식.
- **세션 선택 시**: `getSessionMessages(sid)` →
  `MessageOut[] → ChatMsg[]` 매핑(role `user→me`, `assistant→ai`, `trace` 부착) →
  `setConvos({ ...c, [activeId]: mapped })` + `setSessions({ ...s, [activeId]: sid })`.
  - 진행 중 스트림이 있으면 `stop()` 먼저(025 리셋 흐름과 동일 안전).
- **이어 보내기**: 기존 `send()` 그대로 — `sessions[id]`가 선택 세션이므로 같은 세션에 쌓인다.
  컨텍스트도 로드된 `convos[id]`에서 `apiMessages`로 복원되어 일관.
- **"새 대화"**(`resetConversation`)는 그대로 — 피커에서 "새 세션"도 같은 동작.
- 빈/실패 graceful: 세션 0개면 피커 비활성 또는 "없음", 로드 실패는 message.error 후 무변경.

### C. api.ts
- `listSessions` 시그니처에 `agent_id?: string` 추가(쿼리 직렬화 1줄).
- `getSessionMessages`는 이미 존재 — 재사용.

## 완료 조건(검증)
1. **백엔드 단위/통합**: `GET /sessions?agent_id=<agt>`가 해당 에이전트 세션만 반환,
   타 에이전트 세션 누출 0, 미지의 id면 빈 목록, counts는 전역 유지. (tests 스크립트)
2. **재개 시맨틱(핵심 시나리오)**: Playground에서 `delete_record` 호출 → 승인요청 →
   ApprovalsView 승인 → Playground 복귀 → 피커에서 그 세션 선택 → **승인된 최종 답변이
   메시지로 보이고**, 이어서 한 마디 더 보내면 같은 session_id로 쌓인다(턴 수 증가).
   - 브라우저(시스템 Chrome, Playwright) E2E 캡처로 확인.
3. **무회귀**: `tsc --noEmit` 통과, 기존 세션 페이징(034)·오버라이드(025)·HIL(041) 검증 green.
4. **타자 검증**: 서브에이전트 또는 codex로 백엔드 필터의 누출/엣지(agent 스코프, counts 의미)
   비판적 리뷰.

## 리스크 / 주의
- **세션↔에이전트 키**: SessionOut.agentId = 외부 `agt_...`(UUID 아님). 프론트 Agent는 `id`(UUID)와
  `agentId`(외부) 둘 다 보유 → 필터·매칭은 `agentId`로. (혼동 시 빈 목록 footgun → 검증에서 단언.)
- **오버라이드 상호작용**: 과거 세션을 불러온 뒤 오버라이드를 적용하면 `resetConversation`이
  방금 로드한 대화를 비운다(025 기존 동작). 의도된 동작으로 두되, 회귀 아님을 확인.
- **승인 전 빈 세션**: interrupt 직후~승인 전에는 그 세션에 메시지 0개(세션 행만). 피커엔 뜨지만
  선택 시 빈 대화 — 정상(아직 답변 미생성). 승인 후 메시지 채워짐.

## 구현 결과 / 보강 (실행 중 추가)

### D. 세션 라벨 preview (사용자 피드백: "해시코드만 보여주면 너무 불편")
초안의 피커는 session_id 축약(해시)을 주 라벨로 썼다 — 사용자가 어떤 대화인지 식별 불가. 수정:
- `SessionOut.preview: str | None` 추가. `list_sessions`가 페이지의 세션 pk들에 대해 **첫 사용자
  메시지**를 1쿼리(`role='user'` ORDER BY `(session_pk, created_at)`, 세션별 최초)로 받아 80자
  절단+`…`로 채운다(`_session_previews`). 빈 세션은 `None`.
- 피커/칩: 주 라벨 = `preview`(굵게, 사람이 읽음), 해시는 **보조 메타**로 강등(턴·상태·시각과 함께
  코드폰트 작은 줄). 현재 세션 칩도 preview 우선.
- counts 헬퍼는 `_badge_counts`로 추출(미지의 agent_id early-return에서 재사용).

### 타자(codex) 적대 리뷰로 발견·수정한 동시성/일관성 결함
초안은 happy-path만 초록이었다. codex가 짚은 실결함을 보강:
- **레이스(HIGH)**: `refreshSessions`가 에이전트 전환을 안 봐서 A 응답이 B 피커를 오염 → 항상
  최신 agentId를 가리키는 `activeExtRef`로 도착시점 일치할 때만 반영.
- **로드 레이스/순서(HIGH→부분)**: `sessionLoadSeqRef`(단조 토큰) 도입 — 더 최신 선택이 있으면
  도착분 폐기. `resetConversation`도 시퀀스를 무효화해 pending 로드가 리셋된 대화를 되살리지 않게.
  로드 중 에이전트가 바뀌어도 `targetId`(호출시 activeId)에만 반영.
- **낙관적 고정 롤백**: session_id를 fetch 전 먼저 고정(로드 완료 전 전송해도 올바른 세션)하되,
  **fetch 실패 시 이전 session_id로 롤백**(실패 세션에 묶인 채 남지 않게).
- **다른 에이전트 세션 방어**: 선택 세션의 `agentId`가 활성 에이전트와 다르면 무시.
- **미지의 agent_id**: `agent_pk is None`이면 `== None`(SQL IS NULL)에 의존하지 않고 **명시 단락**해
  빈 페이지 반환(스키마상 비-NULL이지만 방어적).
- **수용한 설계 결정**: `GET /sessions/{id}/messages`는 agent 스코프 미적용으로 둔다 — 어드민
  콘솔은 세션 뷰에서 이미 전 세션·메시지를 노출(같은 테넌트, 보안경계 아님). UX 정확성(엉뚱한
  에이전트 메시지 로드)은 프론트 가드 + 피커 필터로 보장.

## 검증 결과
- **백엔드 통합**(`tests/verify_055_session_agent_filter.py`, 22단언 PASS): agent 필터 누출 0
  (A↔B 양방향), 미지의 id→빈 목록, counts 전역, status×agent 교집합, preview(80자 절단·첫 메시지만·
  빈 세션 None). 자가정리(prefix `sess_v055_`, Message FK CASCADE).
- **브라우저 E2E**(`tests/browser/shot-resume-session-055.mjs`, RESUME055_OK): 대화→이탈(리셋
  재현)→피커 선택→복원→이어보내기, preview 라벨이 피커에 노출. mock LLM은 도구호출 미지원이라
  delete_record 직접 발화 대신 일반 대화로 재개 경로 전체를 행사(승인 후 영속은 041이 커버).
- **무회귀**: `tsc --noEmit` EXIT 0.
- **타자**: codex 적대 리뷰 2라운드(발견→수정확인). agent 필터 누출은 실결함 없음 확인.
