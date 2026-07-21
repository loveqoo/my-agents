# 156 — 도구 승인 오버라이드 + 승인자 연결 P2 (스펙 177 P2)

## 맥락
P1이 "관리자가 도구에 승인 걸기"(기본 정책). P2는 개발자 원래 요구 "매핑 시 편하게 오버라이드 + 승인자"를
실현: 에이전트별로 도구 기본 승인을 강화/완화하고, 승인자(관리자/본인)를 정한다. 완화=관리자만(D4).

## 한 것
- **리졸버 확장**: `resolve_tool_approval(server, tool, tools_meta, tool_policy)` → `{permission, approver}`.
  도구 기본(tools_meta.approval, approver 기본 admin) ◁덮음◁ 에이전트 오버라이드(`config.toolPolicy
  ["mcp:server/tool"].approval`의 required/approver). 두 소비처(build_mcp_tools·broker.approval_for)+resume
  ·eval 배선. approver를 interrupt→`Approval.approver`(신규 컬럼+마이그레이션)에 스탬프.
- **승인자 연결**: `_may_resolve`가 `getattr(approval,"approver")` non-None이면 그 필드로 판정(self→owner만,
  admin→admin만), None이면 기존 Casbin `can_self_approve` 폴백(메모리·A2A·레거시 무회귀).
- **완화 게이트(agents CRUD)**: create/update/clone에서 toolPolicy가 완화 의도면 `is_privileged`만 허용.
- **UI**: 에이전트 편집기에 배선된 MCP 도구별 승인 오버라이드 Select(기본/승인·관리자/승인·본인/승인없음).
  serializer+AgentOut에 toolPolicy 노출(폼 재로드 라운드트립).

## 배운 것
- **권한 게이트를 "가변 기준값과의 비교"로 판정하면 TOCTOU가 생긴다 — 의도의 값 자체로 판정하라(적대 검토 M).**
  처음엔 게이트가 "현재 도구 기본 대비 완화 여부"를 비교했다. 그러면 member가 **아직 승인 없는** 도구에
  `required:false`를 심어두고(그 순간엔 no-op이라 게이트 통과) admin이 나중에 그 도구를 승인 필요로 조이면,
  저장 땐 안 걸렸던 override가 런타임에 승인을 끈다(TOCTOU 우회). 해결 = **값 기반**: override가 완화 의도
  (`required:false`·`approver:self`)를 *표현*하는 저장 자체를 비-admin에 막는다(현재 기본 무관). 그러면 어떤
  버전·시점에도 비-admin 저작 완화가 존재 불가 → promote/activate 재적용도 안전(Low 결함도 동시 무력화).
  일반화: **"쓰기 시점 검사 + 읽기 시점 적용 + 가변 기준값" 3요소가 모이면 TOCTOU**. 기준값을 불변으로
  하거나(값 기반), 읽기 시점 재검사로 깬다. [[installed-guard-isnt-covering-guard]] [[verification-ladder-three-rungs]]
- **인가를 "문자열 매칭" 대신 "명시 필드"로 하면 이스케이프/파싱 공격면이 사라진다.** approver를 permission
  문자열(`mcp.{server}.{tool}`)의 Casbin 매칭으로 판정했다면 세그먼트 이스케이프(`.`/특수문자) 우회 위험이
  있었다(P1 적대 검토 P2 경고). 대신 `Approval.approver`를 명시 스탬프해 `_may_resolve`가 그 필드로 판정 →
  permission은 표시·감사용만, 인가는 필드로 → **이스케이프 자체가 무의미**. D3의 "승인자 도구정책 일원화"가
  보안까지 개선.
- **인터페이스 param 추가는 소비처가 무시해도 "정직하게" 전 구현에 넣는다.** `approval_for`에 tool_policy를
  McpProvider만 쓰지만 6개 provider 전부 시그니처에 추가(기타는 무시). isinstance 분기보다 균일 인터페이스가
  드리프트 0·미래 안전. 스텁/pre-migration 객체 방어는 `getattr(x,"approver",None)`(속성 부재→폴백=의미도 정확).
- **완화 게이트는 뮤테이션 "전 표면"을 열거해 덮어야 한다.** create/update/clone만이 아니라 register(외부)·
  version/activate/revert도 config를 쓴다. 확인: register는 명시 화이트리스트(toolPolicy 미포함), 나머지는
  기존(게이트된) config 복제 → 값 기반 게이트면 비-admin 완화가 애초에 존재 불가라 promote 경로도 안전.
- **요청 오버라이드 허용키에 정책 필드를 넣지 마라.** toolPolicy를 `_load_context` allowed(요청 오버라이드
  화이트리스트)에 **불포함** → config-only. 넣었으면 요청 한 방으로 승인 완화 우회 가능했다.

## 검증
verify_177(리졸버 R1-R8 20 + 게이트 G1-G6[TOCTOU 포함] + reconcile R6)·verify_066(approver 연결 M5 6,
approver가 Casbin보다 우선 핀)·회귀(041·092·171·151)·serializer 라운드트립·브라우저(오버라이드 섹션 렌더).
**적대 검토(deep-reasoner)**: TOCTOU[M] 발견→값 기반으로 봉합, [Low] activate/revert도 값 기반이 무력화,
요청주입·approver오염·두경로드리프트·무회귀는 근거와 함께 기각.

## 남은 것(P3)
`Permission.approver` 죽은 컬럼 제거 + `config.permissions[]` 죽은 필드 정리 + 능력 부여 UI + 문서화.
잠복: 커스텀 impl(신뢰 레지스트리)이 `overrides.toolPolicy`를 직접 build_mcp_tools에 넘기면 우회 가능하나
위협모델 밖(신뢰 코드) — P3에서 명문화 검토.
