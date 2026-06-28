# 038 — 세션 정리 정책 회고 (스펙 049, 마스터 044 배치5·#10)

## 무엇을 했나
0턴 빈 세션이 DB에 쌓이던 문제(#10, #11 정크의 뿌리)를 **두 메커니즘**으로 잡았다.

1. **소스 미영속(근본)**: `_load_context`가 매번 세션 행을 eager INSERT+commit하던 것을 멈추고,
   `session_id` 문자열만 만들어 `ctx["session_pending"]`에 보류 → DB 행 생성을 **첫 `_persist`(실 턴)**까지
   지연(`_resolve_session_for_persist`의 get-or-create). 플레이그라운드를 열고 한 마디도 안 하면 행이 안 남는다.
2. **배치 턴 정리(백스톱)**: `cleanup_sessions`에 `turns < min_session_turns AND last_activity < now-IDLE_GUARD(1h)`
   절을 나이 절과 **합집합**으로 추가. 활성 세션은 IDLE_GUARD가, 충분 대화는 turns≥N이 보호.

사용자가 **옵션3(생성 시점부터 미영속 + 배치 보조)**를 선택(리스크↑ 감수, 가장 근본적). IDLE_GUARD는
어드민 노브가 아니라 내부 1h 상수로 둬 어드민 표면을 `min_session_turns` 하나로 유지.

## 어디서 멈칫했나 — 두 번의 "생성 가드"가 전체를 못 묶었다
- **구현 중 자가 포착**: 소스 미영속으로 바꾸자 **HIL 승인으로 중단된 턴**이 `_persist`에 도달 못 해
  세션 행이 안 생긴다 → resume_approval의 `_load_context`가 행을 못 찾아 새 id 발급 → 대화 고아.
  → `_create_approval`이 행을 lazy-create하도록 보강(승인 게이트=실 턴).
- **적대 리뷰가 그 다음 구멍을 짚음(결함 #1, MEDIUM)**: `_create_approval`이 만든 세션은 `turns=0`.
  `min_session_turns` 설정 시 **배치 턴 정리**가 그 행을 지운다(0<N, 승인 대기가 1h 초과는 흔함).
  Approval 행은 살아남지만(plain string session_id, FK 아님) resume가 또 고아가 된다.
  → `cleanup_sessions`에 **pending approval 세션 제외(`~exists` AND, 양 절 공통)** 추가로 차단.

핵심: 연속성을 **생성 시점에만** 막았더니(첫 가드: _create_approval) **다른 서브시스템(배치 정리)**이
그 행을 지워 깼다. 보장은 *생성→정리* 전 구간(=세션 수명)에 걸쳐야 했다. → learning 048.

## 검증 사다리(3 rung 다 적용)
- **단위/통합(자가)**: verify_049 50 checks ALL PASS. self-fixture(외부 에이전트+`v049_` prefix, agent_pk 자가정리)로
  시드 결합 끊음(learning 045 3번째 적용).
- **파괴 안전**: 라이브 DB에 턴 매치 **126/130건**(실제 #11 정크) → 적응형 가드로 비-fixture 매치 시 실삭제 생략,
  나이 100d 경로만 실삭제. 38식 "오래된 fixture vs 최근 실데이터" 베팅이 **턴 기준엔 안 통함**을 실측으로 확인
  (저턴 이탈은 곧 실데이터라서) → 남의 데이터 0건 삭제(learning 037/034).
- **타자(적대 서브에이전트)**: A~E 5축. session_pk None-deref·경합·cross-agent 누출·합집합·tz·turns NULL 모두 clean,
  결함 #1만 적발 → 수정 + B6 회귀(대조군: 같은 나이 비-승인 세션은 삭제됨).
- **브라우저**: BatchView `최소 턴 수` 필드 + IDLE_GUARD 보호 문구 렌더 확인.

## 다음 작업에 들고 갈 것
- 마스터 044 **배치 050**(파괴적 정리 #1 A2A정크·#11 세션정크·#13 유저정크): #11의 잔존 정크(126건)는 이제
  `min_session_turns` 활성화로 청소 가능하나, **파괴적이므로 dry-run + 적대 리뷰 필수**(learning 037/038).
  050에서 일괄 정리 노브/원클릭을 다룰 때 이 정책을 재사용.
- 참조: [[045-integration-fixture-coupled-to-seed-loses-the-rung]], [[044-a-guard-installed-is-not-a-guard-that-covers]],
  [[048-a-guard-at-one-lifecycle-edge-does-not-cover-the-lifetime]].
