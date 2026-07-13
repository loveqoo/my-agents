# 322 — custom MCP 기본 공개(오픈) + published 영역 설명

## 배경 / 동기

사용자 지적(2026-07-13): **"MCP 사용 조건이 published가 필수더라. UX 관점에서 잘못됐다. 등록하면 모두
오픈(공개)이 기본이어야."**

현 구조: `source=custom`(우리가 코드로 정의·FastMCP로 서빙하는) MCP는 에이전트가 **서빙 엔드포인트**
(`/_served/mcp/{name}/`)로 접속해 쓴다. 그 엔드포인트가 `published`로 열린다(스펙 156). 즉 custom MCP는
**published=on이어야 에이전트가 쓸 수 있다.** 그런데 시드 기본값이 `published=False`라, 바인딩해놔도 조용히
도구 0개가 되는 footgun(`build_mcp_tools`가 연결 실패 서버를 `except: continue`로 조용히 스킵).

사용자 결정: 내부/외부 분리(in-process) 대신 **기본값을 오픈으로** 뒤집는다(단순). custom MCP는 등록/시드
즉시 사용 가능, `published`는 켜진 상태가 기본.

## 설계

### 1) 시드 기본값 반전 — 서빙 custom MCP는 기본 공개

`seed.py _reconcile_served_mcps`(신규 행 생성)의 `published=False` → **`published=True`**. 신규 설치는 서빙
custom MCP(calc-tools·targeting-catalog·web-fetch)가 바로 열려 에이전트가 즉시 사용 가능.

- **기존 행 보존은 유지**(learning sync-wholesale-replace): reconcile은 published를 관리자 저작 필드로
  보존하므로 기본값 변경은 **신규 시드에만** 반영. 기존 dev DB의 서빙 custom 행은 별도 데이터 flip으로
  현 환경도 열어준다(현재 사용 가능하게).
- **재공개 가드는 그대로**(스펙 152/156): `source=custom`만 published 가능·source 불변·사용자 custom
  자가등록 봉인. 기본값만 반전이지 가드 완화 아님.

### 2) published 영역 설명 보강 (BlocksView "외부 서빙" 섹션)

현 문구는 "이 서버의 도구를 LangGraph MCP 프로토콜로 노출합니다"뿐이라 **"공개=에이전트 사용 가능"**이라는
핵심 결과가 안 보인다. 긍정문(copy-rubric)으로 보강:
- 공개 상태의 의미: "에이전트가 이 도구를 사용할 수 있고, MCP 프로토콜로 외부에도 노출됩니다."
- 끄면: "비공개 — 에이전트가 사용할 수 없고 외부 노출도 없습니다." (부정의 부정 회피, "무엇이 가능한가" 축)
- 기본 공개임을 알 수 있게(신규 등록 시 켜져 있음).

## 범위 밖 (OUT)

- 내부/외부 사용 분리(in-process 바인딩) — 사용자가 "그러지 말고 기본 오픈"으로 결정, 이 스펙은 기본값 반전만.
- local/external MCP의 published — 이들은 서빙 대상 아니라 published가 사용과 무관(가드가 true 자체를 차단).
- 서빙 안전성 재검토 — 3개 서빙 도구는 스펙 156 무인증 안전 불변식 통과분(계산·엔티티조회·위키 read-only).
- custom MCP 사용자 자가등록 허용 — 시스템 전용 유지(스펙 156 High).

## 검증

- **단위/데이터**: 신규 시드 시 서빙 custom MCP published=true(빈 DB reconcile 후 조회). 기존 행 보존 불변
  (이미 admin이 끈 행은 재시드가 안 켬 — sync-preserve 회귀). 재공개 가드 무회귀(local published=true=400).
- **기능(브라우저)**: 서빙 custom MCP(calc-tools)를 에이전트에 바인딩 → 채팅서 도구 실제 호출(공개 기본이라
  추가 조작 없이 동작). BlocksView "외부 서빙" 섹션에 보강된 설명 렌더 확인.
- **회귀**: verify_156(서빙 게이트)·verify_211(공개/미공개 404 불변) — 기본값 반전이 이들 전제와 충돌하면
  테스트를 새 기본값에 맞춰 갱신(기본 공개 반영), 가드 시맨틱은 보존.
- tsc/build·ruff/mypy 클린.

## 완료 조건

- 신규 설치에서 서빙 custom MCP가 기본 공개 → 에이전트가 즉시 사용 가능(footgun 소멸).
- BlocksView published 영역에 "공개=사용 가능/외부 노출" 설명이 긍정문으로 표시.
- 재공개 가드·source 불변·사용자 custom 봉인 무회귀.
