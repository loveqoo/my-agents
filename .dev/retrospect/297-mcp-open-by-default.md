# 297 — custom MCP 기본 공개(오픈) + published 영역 설명 (스펙 322)

## 무엇을 했나

사용자가 "MCP 사용에 published가 필수인 게 UX상 잘못됐다, 등록하면 기본 오픈이어야"고 지적 → 서빙 custom
MCP의 시드 기본값을 `published=True`로 반전 + 관리 UI "공개" 영역에 설명 보강.

## 핵심 배운 것

### 1) "사용 조건"이 코드가 아니라 접속 경로에서 나온다 — published↔usage의 숨은 결합
사용자 질문("왜 published가 필수?")에 처음엔 "published는 외부 서빙용, 바인딩은 enabled_tools로"라고 답할
뻔했다. **틀렸다.** custom MCP는 `served_url`(=`/_served/mcp/{name}/`)로만 접속되고, 그 엔드포인트가
published 게이트다(스펙 156). 즉 런타임 코드엔 published 검사가 없어도, **접속 경로가 게이트라 사실상
published가 사용 조건**이다. `build_mcp_tools`는 연결 실패 서버를 `except: continue`로 조용히 스킵 →
바인딩해놔도 도구 0개(footgun). **"검사가 코드에 없다=무관"이 아니라, 접속 토폴로지까지 봐야 결합이 보인다.**
(측정으로 확증: published=true→도구 3개, false→0개, 복원→3개.)

### 2) 단정 전에 재현 — 사용자 보고가 내 첫 모델과 어긋날 때
"published는 사용과 무관"이라는 내 첫 이해와 사용자 관찰("필수더라")이 충돌 → 단정 않고 seed·blocks·
served_mcp·runtime을 정독 → source별로 다름을 확인(local/external=무관, custom=필수). [[probe-deeper-before-concluding]]
그대로: 내 측정(코드에 published 없음)이 사용자 보고와 어긋나면 측정 범위를 의심(접속 경로까지).

### 3) 사용자가 단순안을 고르면 그걸 존중 — 정교함≠정답
나는 "내부/외부 분리(in-process 바인딩)"라는 정교한 안을 제시했으나 사용자는 "그러지 말고 기본 오픈"으로
단순화. custom 서빙 도구 3개는 스펙 156 무인증 안전 불변식 통과분이라 기본 공개해도 안전 → 기본값 반전만으로
footgun 소멸. 큰 리팩터 대신 **한 값 반전**이 사용자 의도(마찰 제거)를 더 곧게 충족.

### 4) 시드 기본값 반전은 두 경로 + 기존 데이터 셋 다
`_reconcile_served_mcps`(alembic 경로)와 `MCP_SERVERS`(create_all 폴백) **두 시드 경로** 모두 반전 필요
(평행 리터럴 드리프트 방지). 그리고 reconcile은 published를 관리자 저작 필드로 **보존**(sync-wholesale-
preserve)하므로 기본값 변경은 신규 시드에만 반영 → **기존 dev DB는 별도 데이터 flip**으로 현 환경도 열어야
사용자가 지금 바로 쓴다.

### 5) copy는 "무엇이 가능한가" 축(긍정문)
"비공개면 못 쓴다"(부정) 대신 "공개하면 에이전트가 이 도구를 사용할 수 있고 외부에도 노출된다 + 기본
공개"(긍정). 미공개 안내도 "지금은 비공개입니다. 공개하면 …할 수 있습니다"로 현 상태(사실)+가능성(긍정).
[[prefer-positive-phrasing-in-copy]]

## 검증
- 기능: `build_mcp_tools(calc-tools)` → published=true 3도구/false 0도구/복원 3도구(footgun 재현+해소).
- UI: BlocksView "공개 (외부 서빙)" 섹션 설명 렌더 스크린샷 확인(토글 ON=기본 공개).
- 회귀: verify_156(9/9)·211(ALL PASS)·lint/mypy/tsc/build 클린.

## 설계 되돌림 명시
스펙 152/156의 "기본 비공개" 방침 반전. 단 **재공개 가드(source=custom만·source 불변·사용자 custom 봉인)는
유지** — 기본값만 반전이지 가드 완화 아님. 서빙 대상은 안전 불변식 통과분(계산·엔티티조회·위키 read-only)
이라 posture 변화 수용 가능(팀 한정 배포 전제).

관련: [[probe-deeper-before-concluding]] · [[whole-fix-over-minimal-patch]] · [[prefer-positive-phrasing-in-copy]] · 스펙 156(custom 서빙)·152(재공개 가드)
