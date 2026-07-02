# 094 — 런타임 tool 배선 인가 (스펙 113)

## 무엇을

codex 112 P0 봉합: 채팅 런타임(`_load_context`)이 agent config `mcps`/`vectorTables` 이름으로 자원을
로드해 복호화 크레덴셜로 tool 배선하던 무인가 경로에 인가를 걸었다. 사용자 "1,2,3,4 모두 차례대로 루프"
의 1번.

## 어떻게

- **주체=에이전트 작성자**(agent.owner_id), 채팅 사용자 아님(공유 에이전트 보존, 112 갈래).
- 단일 헬퍼 `ownership.agent_may_wire`(닫힌 집합 5규칙: NULL-owner 무회귀·작성자 특권·자기 소유·
  published·RBAC per-cap). `_rbac_check`(112 A) 재사용 → 브로커·런타임 배선이 같은 레버.
- 게이트 지점=`_load_context` 단일 관문(chat/a2a/resume 공유). 거부=조용히 skip(존재 비노출).

## 잘된 것

- **112 갈래 교훈을 곧바로 재적용**: "인가 주체는 채팅 사용자가 아니라 작성자"를 처음부터 잡아 공유
  에이전트를 안 깼다(learning 113 ①). NULL-owner=전부 배선으로 무회귀 축 확보(오늘 모든 에이전트).
- **codex가 두 번째 confused deputy를 잡음**: 작성자 권한 게이트를 override 주입이 우회(P0) — 호출자가
  `overrides.mcps`로 남의 MCP를 작성자 권한에 태움. "저장본=작성자·주입분=호출자"로 분리 봉합(113 ②).
  자가검증이면 절대 못 봤을 반례(override 경로를 인가와 별개로 생각했음).
- **P2(non-UUID owner_id casbin role 충돌)도 봉합**: UUID 검증을 casbin보다 먼저(113 ③).
- **3런 검증**: 단위(술어 5규칙) + 실 DB 통합(_load_context 직접: member 남의 것 미배선·NULL-owner
  무회귀·per-cap 레버·published·override 주입 차단·non-UUID 특권 오판 차단) + codex 적대. 110/112/100 무회귀.

## 배운 것 / 함정

- **자원 참조로 크레덴셜 쓰는 경로는 "누가 그 이름을 넣었나"로 인가**(113 ①②) — 저장본은 작성자,
  요청 주입분(override)은 호출자.
- **신원 문자열은 권한조회 전에 형식 검증**(113 ③) — 식별자/역할 이름 공간 충돌.
- **같은 RBAC 레버가 두 경로 커버**(113 ④) — `_rbac_check` 단일 술어라 새 경로도 자동.
- override 화이트리스트는 mcps는 포함/vectorTables는 불포함 → 주입 표면이 mcps에 한정(vt는 무영향).

## 검증 생략 / OUT

- 저장 시점(config 작성 시) 검증 — 런타임 게이트가 진실원(시점 드리프트 회피).
- Collection published 플래그 — RBAC per-cap 레버로 충분.
- 채팅 사용자 축 게이팅 — 의도적으로 안 함(112 갈래).

→ learning 113
