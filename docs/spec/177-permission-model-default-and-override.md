# 177 — 권한/승인 목표 모델: 도구 기본 정책 + 에이전트 오버라이드

> **상태: 설계 초안(AI) — 구남님 검토 대기.** 구현 전 목표 모델 합의용. Cedar 폐기, ABAC 추후.

## 문제 (진단, deep-reasoner 전수 매핑)
"권한 기능은 있는데 제대로 쓰기 어렵다"의 구조적 원인:
1. **화면엔 보이나 런타임에서 죽은 설정 2개** — (a) 에이전트 폼 `permissions[]`는 아무것도 게이트 안 함
   (배지·삭제가드 전용), (b) 권한 블록의 `승인자(user/admin)` 컬럼은 실제 승인자 판정과 단절(진짜는
   Casbin `self_approve` 정책이 결정). → **설정해도 아무 일 없음** = 어려움의 정체.
2. **관리자가 "기본값"을 세울 단일 지점 부재** — 승인 필요 도구는 코드 상수(`_APPROVAL_ACTIONS`, 1개)
   하드코딩, 능력 부여(`add_policy`)는 부팅 시드에만 → 사실상 admin/superuser만 능력 사용.
3. **같은 도구가 두 경로로 배선되며 게이팅이 다름** — 직접형(`config.mcps`, 승인만·per-user RBAC 없음)
   vs 능력형(`config.capabilities`의 `mcp:`, allowlist∩RBAC+승인). 예측 불가.

## 개념 정리 (UI에서 셋만 남긴다)
흩어진 어휘를 사용자에게 **세 가지**로만 노출:
- **능력(도구)**: 이 에이전트가 쓸 수 있는 도구/기능(배선). = 기존 `capabilities`(+직접형 mcps 수렴).
- **누가 쓰나(역할)**: 그 능력을 어떤 역할/사용자가 쓸 수 있나. = RBAC(Casbin), 부여 UI 신설.
- **승인 필요 여부**: 위험한 능력은 실행 전 승인. = 도구 **기본 정책** + 에이전트 **오버라이드**.
(`permissions[]`·`Permission.approver` 죽은 개념은 승인 모델로 흡수 후 정리.)

## 목표 모델

### (1) 도구 기본 정책 — 관리자 수립
저장처 = **`McpServer.tools_meta[tool]`**(이미 admin이 BlocksView서 편집, 라운드트립 보존). 키 추가:
```
tools_meta[tool].approval = { required: bool, approver: "admin" | "self" }
```
- `required=true` → 그 도구 호출 전 승인. `approver` = 누가 승인(관리자 / 본인).
- 관리자 UI: MCP 도구 편집에 도구별 "승인 필요 + 승인자" 설정.

### (2) 에이전트 오버라이드 — 매핑 시
에이전트에 도구를 배선할 때 그 도구의 기본을 덮어씀. 저장 = 에이전트 config의 **도구별 오버라이드 맵**
(신규 `toolPolicy` vs 죽은 `permissions[]` 재활용 — **미결정, 아래 D1**).
```
config.toolPolicy[cap_id] = { approval?: { required?, approver? } }  # 미지정 키는 기본 상속
```
- 예: 도구 기본은 "승인 불요"인데 이 에이전트에선 "승인 필요"로 강화(또는 반대로 완화 — D2).

### (3) 단일 승인 리졸버 — 하드코딩 제거
```
resolve_tool_approval(server, tool, agent_config) -> {permission, approver} | None
  = 도구 기본(tools_meta)  ◁덮음◁  에이전트 오버라이드(config.toolPolicy)
```
- **두 소비처가 이 리졸버 하나를 공유**(드리프트 0): `runtime._wrap_mcp_tool`(그래프-tools)·
  `broker.McpProvider.approval_for`(조율형). 기존 `_APPROVAL_ACTIONS` 상수 제거(또는 시드 기본으로 이전).
- permission 문자열은 파생(`mcp.{server}.{tool}`) — 승인 카드·감사에 표시.

### (4) 승인자 연결 — 죽은 컬럼 소생
`approver`(admin|self)를 **실제 승인 판정에 연결**: 리졸버가 낸 approver로 approval을 스탬프하고,
`approvals._may_resolve`가 이 값을 읽어 self/admin 결정(현재 Casbin `self_approve` 문자열 정책과
일원화). `Permission.approver`는 이 소스로 살리거나 제거(D3).

### (5) 능력 부여 UI — 최대 병목 해소
관리자가 역할/사용자에 `capability:{kind}[:resource]`를 부여하는 엔드포인트+UI(`add_policy` 래핑,
`require("users","manage")` 보호). 없으면 member는 능력을 영영 못 씀. (Phase 늦춤 가능.)

### (6) 두 경로 비대칭 — 수렴 또는 명문화
직접형 `config.mcps` 도구에 per-user RBAC 부재(설계 경계인지 갭인지 스펙 100/106 재확인). 최소한
**승인 리졸버는 두 경로 공통 적용**(3)이라 "승인은 어느 경로든 일관". RBAC 수렴은 후속.

## 단계 (구현 순서 — 각 단계 = 별도 스펙, per-spec 커밋)
- **P1 ✅ 완료(2026-07-04)**: (3) 리졸버 통합 + (1) 도구 기본 승인 정책(tools_meta) + admin 편집 UI. →
  "관리자가 데이터로 승인 설정" 실현. `resolve_tool_approval`(runtime) 하나를 그래프-tools·브로커 두
  경로가 공유(drift 0), tools_meta 우선·레거시 `_APPROVAL_ACTIONS` 폴백(delete_record 무회귀). schemas
  검증기가 approval 키 보존, BlocksView 편집 폼에 도구별 "승인 필요" 토글. 검증: verify_177(리졸버×reconcile
  왕복 13/13)·브라우저 3/3·종단 UI→DB→리졸버·회귀(041·092·151). **적대 검토(deep-reasoner)가 P0 발견**:
  rediscover가 `_tools_meta_from_details`로 tools_meta 통째 교체 시 admin approval 소멸 → `prior` 이월
  보존으로 봉합(회고 155). approver(admin/self) 선택 UI·완전 연결은 P2.
- **P2**: (2) 에이전트 오버라이드 + (4) 승인자 연결. → "매핑 시 편하게 오버라이드" 실현.
- **P3**: (5) 능력 부여 UI + 죽은 설정 정리(permissions[]/approver) + (6) 문서화.

## 검증 접근
- 리졸버는 **단위 매트릭스**(기본×오버라이드×approver)로 결정성 핀. 라이브는 조율형+도구로 승인 발화
  (learning 144). UI는 브라우저 왕복. **적대 검토(deep-reasoner)**: 두 경로 일관·무회귀·fail-closed 유지.
- 마이그레이션(tools_meta 키 추가·config 필드)은 무회귀(미지정=기존 동작).

## 확정된 결정 (구남님, 2026-07-04)
- **D1 오버라이드 저장 = 신규 `config.toolPolicy` 맵.** 죽은 `permissions[]`는 P3에서 제거.
- **D2 오버라이드 방향 = 강화·완화 둘 다.** 에이전트에서 도구 기본 승인을 켜고 끌 수 있다(관리자 기본이
  하한이 아님).
  - ⚠️ **보안 고려(P2 설계 시 반영)**: 완화(기본 필요→불요)는 관리자가 건 승인을 에이전트 편집으로 끄는
    행위다. 에이전트 편집은 소유자/관리자 게이트(assert_may_manage)라 아무나 못 하지만, **"완화"만
    별도 권한(예: admin)으로 한 겹 더 게이트**할지 P2에서 결정(강화는 자유, 완화는 특권 후보). 감사
    로그에 오버라이드 방향 기록.
- **D3 approver 소스 = 도구 정책(approval.approver)으로 일원화.** `Permission.approver` 컬럼은 제거
  (P3, 개념 중복 해소). 승인자 진실원은 도구 기본 정책 ◁덮음◁ 에이전트 오버라이드 하나뿐.

## OUT
- ABAC(추후). Cedar(폐기). 승인 후 라이브 재개(개선 B, 별도). member fine-grained RBAC 정책 언어.
