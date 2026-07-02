# 098 — A2A 협업 실증 + 위임 승인 게이트 (스펙 117)

## 무엇을

플랫폼 존재 이유(다중 에이전트 A2A 협업)의 빈 곳: `AgentProvider`(kind=agent)는 배선됐으나 **성공
협업을 관통 실증한 적 없고**(verify_100 H4는 원격 에러) `approval_for=None`(위임 승인 소스 없음). 방향 1
(사용자 "4개 방향 모두 차례대로")의 첫 항목.

## 어떻게

- Part A: a2a_stream 패치(결정적 프레임)로 조율형→A2A 위임을 채팅 1턴 관통 — 원격 성공·1회 호출·질의
  도달·종합 발화 4단 실측.
- Part B: `AgentProvider.approval_for`를 대상 `config.requires_approval` **opt-in**(기본 off=무회귀)으로.
  provider.approval_for 시그니처를 `(row, cap_id, args)`로 통일(invoke가 받는 row 재활용), `_a2a_text`
  공유(승인==전송). 게이트=전송 이전 interrupt(스펙 101 재사용).

## 잘된 것

- **"실행됨 vs 성공함" 구분**(learning 117 ①): verify_100 H4가 노드 존재만 봤음을 간파, 원격을 결정적
  성공시켜 이음매(질의 도달)·호출횟수까지 실측. 노드 타임라인은 실패도 초록이라 성공 경로 재현이 핵심.
- **codex가 write-schema 드롭을 잡음**([P1] requires_approval가 AgentConfig에 없어 라운드트립서 소실 —
  verify_117이 DB 직시드라 초록, learning 101 재현). 스키마 필드 추가 + **B0 라운드트립 가드**로 봉합.
  자가검증이면 "테스트 초록"에 속았을 것 — 적대 타자가 seed 우회를 짚음.
- **경계를 좁혀 문서화**([P1#2] 승인==전송이 재개 args 비결정이면 깨짐): 기본 orchestrate 경로는
  state["query"]+116 커밋으로 안전 → 보장을 그 경로로 좁혀 문서화(넓게 주장 안 함). [P2] 비-dict config
  방어도 즉시 봉합.
- **검증 3런**: HTTP E2E(관통) + 단위(approval_for opt-in·승인==전송) + 그래프 통합(interrupt 이전 전송 0·
  approve 1·reject 0 fail-closed). 브로커 6 provider + 오케스트레이션 전 시리즈 무회귀(시그니처 일괄 변경).

## 배운 것 / 함정

- **노드 실행 ≠ 협업 성공**(117 ①) — 성공 경로 결정적 재현으로 실증.
- **정책 config 값은 write-schema 관통 + 라운드트립 실측**(117 ②, seed 우회 금지).
- **부수효과 게이트는 대상별 opt-in 기본 off**(117 ③, 무회귀).
- **sync 콜백엔 이미-resolve된 값을 시그니처로 넘겨라**(117 ④).
- **"승인==실행" 등식은 성립 범위로 좁혀 문서화**(117 ⑤).

## 검증 생략 / OUT

- 다중 A2A 순차 승인 표면화(116 다중 interrupt OUT, 안전 fail-closed 유지)·승인 payload args 스냅샷
  바인딩(재개 args 안정 일반보장)·a2a.delegate self-approve 시드(현재 admin만=fail-closed)·실 네트워크 CI.

→ learning 117
