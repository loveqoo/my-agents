# 152 — 외부 유래 재공개 금지 (실사용 #5, B 시리즈 선행 보안 경계)

## 요구 (사용자 2026-07-03)
외부에서 제공받은 에이전트와 MCP는 다시 외부로 오픈하지 못해야 한다.

## 현황 실측
- **에이전트: 이미 봉인**(스펙 083) — expose_agent가 source!=ui에 400(proxy-of-proxy 거부) +
  a2a_server가 non-ui를 404로 접는 이중 게이트. private 봉인(147)도 별도 존재.
- **MCP: 구멍** — 상세 UI는 external에 공개 스위치를 숨기지만 API는 안 막는다:
  ① `PUT /mcp-servers/{id}/publish` published=True를 source 무관 허용
  ② `POST /mcp-servers` published=True + source=external로 생성 가능
  ③ `PUT /mcp-servers/{id}` 로도 동일 우회. (installed-guard≠covering-guard — 147·150과 동형)

## 설계
- 3입구 모두에서 **published=True ∧ source=external → 400** ("외부에서 가져온 MCP는 다시 외부로
  공개할 수 없습니다"). **끄기(published=False)는 source 무관 항상 허용**(stale 플래그 멱등 청소 —
  083 관례와 동일). update는 결과 상태 기준(source·published가 동시에 바뀌어도 판정).
- 서빙측 이중 게이트: published 소비 지점에서 external을 접는 방어선은 추후 커스텀 MCP 공개(#4)
  스펙에서 서빙 경로와 함께 다룬다(현재 published는 표시 플래그 — 실제 프록시 서빙 없음).

## 검증 (2026-07-04 완료)
- verify_152 11/11: publish 켜기 400/끄기 허용·생성 400·update 우회 400(동시 변경 포함)·local
  publish 정상·에이전트 기존 봉인 핀·**source 불변 400**·**오염 행 런타임 배선 차단**(V6 —
  external+published를 ORM으로 직접 심어도 _load_context가 걸러냄, 로그 실측).
- codex: High 1(source 세탁 — external→local로 바꾼 뒤 publish → source 생성 후 불변으로 봉인)·
  Medium 1(소비 지점이 published만 믿음 — 배선 술어에 external이면 published 무효 fail-closed)·
  나머지 입구 전수(seed=local뿐·rediscover는 published/source 불변) 확인 → 2건 수정.
- e2e 생략(사유 기록): UI 무변화(스위치는 이미 숨김) — API 봉인만이라 브라우저 검증 대상 없음.

## 잔여 경계(정직)
- 생성 시점 provenance 자기 신고(외부 URL을 source=local로 등록)는 막을 수 없다 — source는
  등록자의 선언이며, 등록자 책임 경계. 시스템이 보장하는 것은 "external로 들어온 것의 세탁 불가".

## OUT
- published의 실제 서빙(프록시) 경로 — #4 커스텀 MCP 공개 스펙에서.
