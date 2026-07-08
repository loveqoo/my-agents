# 스펙 244 — 버전 운영 화면 (AgentOps D)

## 배경 (로드맵 D — 마지막 조각)

"Version 하나가 운영 단위" — 버전별 피드백 수/비율·평가 이력·회귀 결과를 에이전트 상세에서 한눈에.
데이터 축은 이미 있다: EvalRun.agent_version(240)·trace.agentVersion(242)·MessageFeedback(209).

## 변경

### 백엔드 — `GET /agents/{agent_id}/ops`
- 버전별 집계: `{version: {evalRuns, lastScore, lastRunAt, autoRuns, feedback: {up, down}}}` +
  `unversioned.feedback`(242 이전 메시지 — 버전 미기록분의 정직한 분리, "버전 미상"으로 표기).
- 평가: EvalRun(agent_pk=이 에이전트) 버전별 count·최근 score·자동 회귀(env.trigger=activate) 수.
- 피드백: MessageFeedback→Message→Session(agent_pk) 조인, `Message.trace->>'agentVersion'`로 버전 귀속.
- 게이트: 에이전트 가시성(may_use_agent) — 상세와 동일(비가시 404-fold).

### UI — 상세 드로어 버전 이력 확장
- VersionHistory 행에 운영 칩(옵셔널 prop — 다른 소비자 무회귀): `평가 94% · 3회` `자동회귀 1` `👍4 👎1`.
  데이터 없으면 칩 생략(무소음).
- 버전 미상 피드백이 있으면 이력 아래 한 줄: "버전 미기록 피드백 👍N 👎M (242 이전 대화)".

## 검증
- verify_244: 채팅→피드백→평가 실행 후 ops가 버전별로 정확 집계(귀속 인과: v1 턴 피드백은 v1에만).
  비가시 에이전트 404. 브라우저: 상세 드로어 버전 행에 칩 노출. codex 적대(집계 누수·타 에이전트 혼입).

## 완료 조건
- 에이전트 상세에서 버전마다 "성적·피드백"이 보이고, 어떤 버전이 낫은지 비교가 화면에서 끝난다.

## 검증 결과 (2026-07-08)
- **verify_244 8/8**: v1 턴 피드백→v1 귀속(인과) · v1 평가 집계 · v2 활성화 자동 회귀=v2 집계·v1 불변
  (버전 분리) · 타 에이전트 혼입 없음 · 비가시 404 · **공유 에이전트 멤버 403(관리자 전용)**.
- 브라우저: 상세 드로어 버전 행에 "평가 100% (최근 성공) · 1회" 칩. tsc 0. verify_241/242 무회귀.
- codex 4건 전부 수정:
  - **#1 조인 불일치 누수** → Message.session_pk=Feedback.session_pk 조인 강제(보정/버그 행 방어).
  - **#2 노출 정책** → 운영 지표는 관리자·소유자 전용(403), UI도 can_manage 게이트.
  - **#3 limit 500 조용한 캡(실버그, no-silent-caps 위반)** → SQL 전수 집계(GROUP BY + DISTINCT ON
    최근 성공)로 교체 — 과소집계 소멸.
  - **#4 lastScore 의미 모호** → "최근 성공" 라벨 명시 + errorRuns 필드·실패 칩(실패가 숨지 않음).
