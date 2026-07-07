# 스펙 234 — 메모리 회상을 타입별 게이트 (233 발견 봉합)

## 배경 (사용자 질문 "메모리 설정은 거짓입니까?" 2026-07-08)

스펙 233 매트릭스가 발견: `config.memories` 회상은 impl 실행 전 **플랫폼 선처리**라 impl의 `consumes`와
무관하게 발동했다. 그런데 편집 폼(AgentForm.tsx:307)은 consumes에 기억이 없는 실행 방식에 대해 **"이
실행 방식은 기억 설정을 읽지 않습니다 — 무시됩니다"**라 경고한다 → 도구·문서엔 참이나 **기억엔 거짓**
(artifact류는 실제로 회상). 사용자 결정: **런타임을 폼 주장에 맞춘다(타입별 게이트)**.

## 변경 (packages/api/src/api/chat.py)

- 신규 chat 경로(`used_memory`, ~742)와 승인 재개 경로(~1250) **둘 다**(이중 배선 축 — codex 잔여 회귀
  지적)에 게이트 추가: `impl.describe().consumes`에 `"memories"`가 있을 때만 회상·자동기록.
  `consumes=None`(미선언)은 게이트 면제(스펙 206 "폼 전부 노출" 계약과 정합 — 무회귀).
- read(회상)와 add(자동기록) 둘 다 `used_memory` 재사용이라 함께 꺼짐(일관).

## 검증
- verify_233: artifact×memory가 발동(회상 hit)→**IGNORE-OK(신호 0)**로 뒤집힘. default/plan_execute/route는
  여전히 회상(consume memories), 전 impl 무능력 대조군 회상 0. PASS 27 + IGNORE-OK 29, VERIFY233_OK.
- codex 적대: consumes=None 정합·브로커 memory 독립·default/A2A 무회귀 확인, 재개 경로 잔여 회귀 지적→봉합.

## 비고
- 브로커 memory cap(capabilities `memory:user`)은 이 게이트와 **독립**(PolicyScopedBroker RBAC 경로). 조율형은
  선언적 위임이라 그대로 발동.
- 폼(AgentForm)은 무변경 — 이 게이트가 기존 "무시됩니다" 경고를 참으로 만든다.
