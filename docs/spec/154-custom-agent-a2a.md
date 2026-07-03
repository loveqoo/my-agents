# 154 — 커스텀 에이전트 A2A 공개 (실사용 #3 + 백로그 ③ 승격)

## 요구 (사용자 2026-07-04)
공통 인터페이스(CustomAgent Protocol)로 구현한 에이전트와 직접 코딩(SDK 배포)한 에이전트를
A2A로 공개할 수 있어야 한다 — "커스텀은 A2A 공개가 안 된다고 알고 있다".

## 원인 실측 (막힌 지점 2개)
1. **private 게이트(147)**: UI/등록으로 만든 에이전트는 전부 owner 스탬프 → private → "private는
   A2A 불가". **공통 인터페이스 구현체(ui+impl)도 이 게이트에 걸린 것** — 서빙 파이프라인
   (stream_local_reply)은 impl을 이미 해석하므로 public이면 노출 동작. → **승격 기능이 진짜 열쇠**
   (147 OUT이던 백로그 ③을 여기서 흡수).
2. **source 게이트(083)**: source=code(SDK 배포)는 proxy-of-proxy 거부로 노출 불가. 직접 코딩
   배포분을 공개하려면 **우리 A2A가 중계(릴레이)** 해야 함. external은 152 봉인 유지.

## 설계
### A. 공개/비공개 전환 (승격·강등)
- `PUT /agents/{id}/visibility {public: bool}` — 소유자/특권만(assert_may_manage).
  - 승격(public=True): owner_id → None (147 의미론 그대로 — public=모두 사용). 이전 금지(069)와
    구분: 타인으로의 이전이 아니라 **소유 해제**이며 소유자 본인/특권의 명시 행위.
  - 강등(public=False): owner_id ← 요청 주체(재-스탬프). **A2A가 켜져 있으면 자동 off**(private+
    A2A 조합 불변식 유지). 경계(정직): 승격→강등을 거치면 원소유자 기록은 소실(마지막 강등 주체가
    소유자) — provenance가 아니라 접근 제어 축이므로 수용.
- UI: 에이전트 드로어에 전환 컨트롤(private↔public, 확인 문구 포함), 목록 태그는 기존 OwnerTag.

### B. code(직접 코딩·SDK 배포) A2A 중계 공개
- expose_agent: source 게이트를 `external만 400`으로 완화(ui·code 허용). private 게이트 유지.
- a2a_server: `_load_exposed_ui_agent` → ui|code 허용. 카드는 기존 형태(이름·우리 relay url·버전).
- message/send·stream: source=code면 `a2a_client.a2a_stream(agent.endpoint, 복호 token, text)`으로
  중계(SSRF 가드·캡·타임아웃 기존 그대로) — text 프레임 포워드, error 프레임은 JSON-RPC error로.
- **루프 가드**: 중계 요청에 `x-my-agents-relay: 1` 헤더 부착, a2a_server는 이 헤더가 있는 요청의
  실행을 거부(-32000 "중계 루프") — 자기/상호 참조 사이클을 2번째 홉에서 절단. 직접 호출(플레이
  그라운드·외부 소비자)은 헤더가 없어 정상. 1홉 중계만 허용(v1).

## 검증 (2026-07-04 완료)
- verify_154 12/12: 승격/강등(재스탬프·A2A 자동 off·no-takeover·머신 400·비소유 404-fold)·
  ui+impl 루프백(카드+message/send 실행, impl 해석 실측)·code 실중계(mock A2A 응답 수신)·
  루프 가드 -32000·external 400(152 무회귀).
- e2e 16/16: 공개 범위 박스·전환 모달/토스트·복귀·code 드로어 중계 스위치 — 시드 에이전트 상태
  사전/사후 curl 실측 원복(예외 시 안전망 강제 원복 동작 확인).
- codex High 0. Low 1 수정(목록 A2A 컬럼이 code에서 숨김 → external만 숨김). 판정 3건은 아래
  경계로 기록.

## 경계(정직 — codex 판정)
- **member 셀프 승격은 의도된 기능**: 147 트리("public=모두 도구처럼 사용")·저마찰 철학 부합,
  admin이 강등으로 회수 가능. public 카탈로그는 admin-curated가 아니다(명시).
- **루프 가드는 1홉 표식(평문 헤더)** — 자기참조 실수 방지용. 헤더를 제거하는 중간 프록시를
  등록하면 다홉 우회 가능(등록자 신뢰 경계). 서명 홉 토큰·사이클 캐시는 OUT.
- **중계의 원격 Bearer=등록 시 저장한 토큰** — public code 에이전트를 켜면 모든 인증된 소비자의
  요청이 등록자 토큰으로 대리 실행된다(스위치 문구에 "중계" 명시).
- allowlist 회수는 10초 TTL·DB 장애 시 스냅샷 유지(기존 동작) — 중계로 영향면이 넓어짐.

## OUT
- 다홉 중계·중계 캐싱. 스킬 확장(#7)·플레이그라운드 A2A 루프백 테스트(#8)는 후속 스펙.
- 강등 시 진행 중 세션 처리(사용 게이트가 다음 로드에서 fail-closed — 즉시 절단은 후속).
