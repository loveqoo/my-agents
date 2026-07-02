# 093 — 공유 카탈로그 소유권 + per-cap 인가 (스펙 112)

## 무엇을

브로커 능력 인가를 kind 단위에서 **능력별(per-cap)**로 좁히고(축 A), Agent·McpServer·Collection에
**소유권(owner_id)**을 붙여 카탈로그 관리(수정/삭제)를 소유자/특권으로 게이트(축 B). 사용자 요청
"인가강화" + "지금 끝까지(막는 것까지)".

## 어떻게 (핵심 결정)

- **축 A(per-cap)**: `_rbac_check`가 kind-레벨 OR `capability:{kind}:{name}` 판정. discover의 name=None
  게이트는 "이 kind에 부여가 하나라도?"로 DB 접촉 전 거부(DB-회피 보존). mcp 서버단위 부여는 툴을 덮음.
- **축 B(소유권)**: `ownership.py` 단일 헬퍼(owner_of/next_owner/may_use/is_privileged/assert_may_manage).
  생성 6입구 스탬프 + 관리 14입구 게이트. NULL-owned=특권만(fail-closed 070), 이전 금지(069), 404-fold(068).

## 잘된 것

- **설계 갈래를 구현 중에 잡아 사용자에 올렸다**: "브로커 invoke를 소유권으로 막자"는 첫 직관이 공유
  에이전트를 깬다는 걸 배선 전에 발견 → 멈추고 "소유권=관리 게이팅"으로 방향 정정(learning 112 ①).
  틀린 축에 도구를 댔으면 멀쩡한 공유가 깨졌을 것.
- **게이트 추가가 기존 열린 문을 드러냈다**: 카탈로그 변경 라우트가 인증만(아무 member나 남의 것 수정/삭제)
  → 소유권 게이트로 닫음. 부수적으로 실 취약점 봉합.
- **적대 검증(codex rung3)이 값을 했다**: 내가 빠뜨린 메모리 변조 3라우트(P1)·404-fold body 누출(P1)·
  mcp 서버단위 per-cap 미확장(P2)을 잡음. 셋 다 봉합. P0(런타임 tool 배선 우회)는 112 이전부터의 별개
  경로라 **정직하게 OUT 문서화**(닫았다고 주장 안 함).
- **3런 검증**: 단위(헬퍼·_rbac_check·per-cap) + 실 DB+ASGI 통합(스탬프·타member 404·본인OK·특권OK·
  NULL-owned·메모리게이트·404-fold body) + codex 적대. 브로커 100–105/111·conformance 089 무회귀.

## 배운 것 / 함정

- **소유권은 "관리"를 막지 "사용"을 막지 않는다**(learning 112 ①) — 공유 자원의 핵심 구분.
- **404-fold는 status가 아니라 body까지 통일**(112 ③) — `not_found_detail`로 라우트 존재-404와 일치.
- **enforcer를 인자로 즉시 평가하면 지연 단락이 깨진다**(112 ④) — ASGI 테스트가 lifespan 미가동이라
  터졌고, 헬퍼 지연 로드로 해결. verify_100의 머신토큰 삭제 경로가 이걸 처음 드러냄.
- **머신 토큰 특권은 맥락마다 다르다**(112 ⑤) — 오케스트레이션 deny vs 관리 특권, 둘 다 정상.

## 검증 생략 / OUT

- 런타임 tool 배선(config mcps/vectorTables) RBAC — 별도 스펙(codex P0, 정직한 경계).
- 에이전트 메모리 **읽기**는 기존대로 router-auth(변조만 게이트).
- owner_id를 API 응답에 노출(UI 소유자 표시) — 집행에 불요, 후속 UI 작업.
- 다중 owner·팀/조직 스코프 — RBAC 도메인 확장 별개.

→ learning 112
