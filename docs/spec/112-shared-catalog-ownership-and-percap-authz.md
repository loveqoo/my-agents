# 112 — 공유 카탈로그 소유권 + per-cap 인가 (인가 입도 강화)

## 배경 / 왜

브로커 능력 인가는 현재 **kind 단위**(`capability:{kind}` invoke)다. Agent·McpServer·Collection은
**owner 없는 공유 카탈로그** → member에게 kind RBAC를 주면 그 kind의 **allowlist 전부** 호출 가능
(codex 100/101 [P1] #1/#2 수용·명시 경계). 오늘은 admin/superuser만 브로커를 쓰므로 *활성 취약점은
아니지만*, member에게 세분 권한을 안전하게 주려면 입도를 높여야 한다. 사용자 요청 "인가강화"의 뒤 절반.

메모리 kind(104/105/111)는 principal-도출 user_id로 이 빚을 그 kind에 한해 갚았다. agent/mcp/rag는
여전히 공유. 소유권 경계 스펙 → RBAC 체크리스트 자동 적용.

## 두 축

### A. per-cap 인가 (마이그레이션 없음)

브로커 `rbac_allows`가 kind 단위만 판정 → **per-cap 판정 추가**: `capability:{kind}:{name}`(예
`capability:rag:docs_kb`)를 먼저 보고, 없으면 `capability:{kind}`로 폴백(하위호환). admin은 `*,*`로
그대로 전부. 이러면 admin이 특정 cap만 member에 부여 가능 → blast radius를 cap 단위로 축소. 정책 모델
파일 불변(casbin obj 문자열만 세분화), 시드 불변(deny-by-default 유지).

### B. 자원 소유권 → **관리 접근 제어** (스키마 마이그레이션 + 라우트 게이팅)

Agent·McpServer·Collection에 `owner_id`(nullable) 추가.

> **구현 중 발견한 설계 갈래(중요).** 소유권으로 **브로커 invoke**를 막으려던 첫 직관은 **틀렸다**:
> admin이 모두를 위해 만든 공유 에이전트를 member가 못 쓰게 되어 **공유 에이전트가 깨진다**. 게다가
> codex가 짚은 "member가 kind allowlist 전부 호출" 빚은 **이미 축 A(per-cap)로 봉합**됐다. 따라서
> 소유권의 **정당한 용도는 "관리(수정/삭제) 접근 제어"** — *누가 카탈로그 항목을 편집/삭제하나* — 이지
> *누가 채팅에서 그 에이전트를 쓰나*가 아니다. 이게 **현존 구멍**도 닫는다: 오늘 카탈로그 변경 라우트는
> `_auth=[Depends(current_principal)]`(인증만) → **로그인한 아무 member나 남의 에이전트/도구/문서를
> 수정·삭제** 가능. 소유권 게이트가 이걸 owner/특권으로 좁힌다.

- **모든 생성 입구에 owner 스탬프**(열거, 빠뜨리면 NULL-owned 고아): Agent=POST ``·`/register`·
  `/connect`·`/external`(4개!) / Collection=POST `` / McpServer=POST `/mcp-servers`. → `owner_of(principal)`.
- **관리(수정/삭제) 라우트에 소유권 게이트** `assert_may_manage(resource, principal)` — 특권 or 소유자
  본인만, 아니면 **404-fold**. Agent=update/delete/versions/activate/revert/expose/resync(7) /
  Collection=update/delete/documents(적재)/documents(삭제)(4) / McpServer=update/delete/publish(3).
- **특권 정의**(`is_privileged`): 머신 토큰(str principal)=신뢰 서비스 자격(전권, 위협 모델 밖·무회귀) ·
  superuser=전권 · admin 역할(casbin `*,*`)=전권 · **그 외 member=비특권**(자기 소유만). enforcer는
  **지연 로드**(머신·superuser는 casbin 미접촉), 미초기화(ASGI 테스트가 lifespan 미가동)면 비특권 안전측.
- **기존 행 = NULL-owned → admin 전용(fail-closed, 070)**. 오늘 카탈로그는 admin 저작이라 무회귀.
  단 *과거 member가 열린 라우트로 만든 행*은 NULL이라 그 member가 못 고침 → 070 self-lockout의 정당한
  조임(admin이 관리). 문서화.
- **소유권 이전 기본 금지**(069) — `next_owner(existing,new)`=기존 보존(수정/버전이 owner 미덮어씀).
- **단일 헬퍼**(`ownership.py`)로 소유 판정, **존재 비노출**(볼 수 없는 자원 404-fold, 068).
- **자가-잠금 핀**: owner 본인은 자기 자원 관리 가능(070).

## RBAC 체크리스트 답변 (요지)

1. **입구 열거**: 브로커 invoke(per-cap, 축 A) + 카탈로그 생성 6입구 + **관리 라우트 14개**(수정/삭제/
   version/activate/revert/expose/resync/documents/publish). 브로커 invoke는 소유권으로 막지 **않음**(공유
   에이전트 보존 — 위 갈래). **비-SQL(체크리스트 §2d)**: 게이트는 SELECT-WHERE가 아니라 이미 로드한
   resource에 대한 판정(라우트가 존재 404 먼저 → 그다음 소유 게이트), agent_id·collection_id 경로로 자원
   특정 후 판정이라 TOCTOU 없음.
2. **입구별 소유권**: 생성=`owner_of`로 1회 스탬프 / 관리(수정·삭제·version·publish 등)=`assert_may_manage`
   (owner or 특권, 아니면 404-fold) / 이전=`next_owner` 기존 보존.
3. **단일 헬퍼**: `ownership.py`(owner_of/next_owner/may_use/is_privileged/assert_may_manage) 드리프트 0.
4. **존재 비노출**: 비소유·NULL-owned 모두 404-fold(403과 구분 안 함).
5. **검증 사다리 3런**: 단위(헬퍼 시맨틱·_rbac_check·broker _permitted per-cap) + 실 DB+ASGI 통합(스탬프·
   타 member 404·본인 OK·특권 OK·NULL-owned member 거부/특권 OK) + codex 적대(여집합).
6. **자가-잠금 핀**: owner 본인 수정 OK(H3)·특권 NULL-owned 접근 OK(H5) 별도 케이스.

## 결정 / 근거

- **소유권 = 관리 게이팅**(invoke 게이팅 아님). 사용자와 합의: 발견한 갈래를 설명 → "지금 끝까지(막는
  것까지)" 선택. 브로커 invoke는 축 A(per-cap RBAC)가 담당, 소유권은 카탈로그 CRUD 접근을 담당.
- **머신 토큰=관리 특권**: 브로커 오케스트레이션에서는 머신 토큰을 deny(유저 세션 대상)했지만, 카탈로그
  관리에서는 신뢰 서비스/CI 자격이라 특권 — 두 맥락이 다르다. 위협은 로그인 member.

## codex 적대 검증 결과 (rung 3)

- **[P1] 에이전트 메모리 변조 라우트 게이트 누락** — add/update/delete `/agents/{id}/memory` 3곳에
  `assert_may_manage` 없었음(빠뜨린 입구). **봉합**(principal 주입 + 게이트, `not_found_detail` 통일).
- **[P1] 404-fold detail 누출** — 미존재="agent not found" vs 비소유="not found"로 body 차이 → 존재 누출
  (068 위반). **봉합**: `assert_may_manage(not_found_detail=...)`로 라우트 존재-404 detail과 일치시킴.
- **[P2] mcp 서버단위 per-cap이 툴로 확장 안 됨** — `capability:mcp:{server}` 부여가 `{server}/{tool}`
  호출을 안 덮어 과잉 제한(보안 상승 아님, 기능 회귀). **봉합**: `_rbac_check`에 서버 폴백(allowlist 시맨틱 일치).
- **[P0→OUT] chat 런타임 tool 배선이 per-cap 우회** — 아래 OUT 참조(정직한 경계).

## 비목표 (OUT)

- **⚠️ 런타임 tool 배선(config `mcps`/`vectorTables`)은 per-cap/소유권으로 막지 않는다 (codex P0, 정직한
  경계).** per-cap 인가(축 A)는 **브로커** 경로만 게이트한다. 기존 채팅 런타임은 agent config의 `mcps`/
  `vectorTables` 이름으로 `McpServer`/`Collection`을 로드해 복호화 크레덴셜로 tool을 배선하는데, 여기엔
  RBAC/소유권 검사가 없다(112 이전부터 존재하는 별개 경로). **에이전트를 설정할 수 있는 주체는 임의 MCP/
  컬렉션을 이름으로 참조해 그 크레덴셜을 런타임에 쓸 수 있다.** 현 위협 모델(admin만 사용)에선 비활성이나,
  member에 세분 권한을 실제로 열려면 **런타임 tool 배선에 RBAC/소유권을 거는 별도 스펙**이 필요하다. 이
  스펙(112)은 그걸 닫았다고 주장하지 않는다 — 브로커 per-cap + 카탈로그 관리 게이트까지가 범위.
- 에이전트 메모리 **읽기**(list/search)는 기존 설계 의도대로 router-auth만(변조만 게이트, 기밀성은 별개).
- 카탈로그 커지면 벡터/하이브리드 검색(설계결정 10) — 별개.
- memwrite admin owner-only resolve/args 마스킹(codex 105 P2) — 별개 저위험 후속.
- 다중 owner·팀/조직 스코프 — RBAC 도메인 확장은 별개(모델 파일 교체 지점만 열어둠).
