# 206 — 실행 방식 매니페스트에 소비 표면 선언 + 폼 게이트

## 배경 (사용자 "순서대로" ② — 201 후속2의 구조적 해법)
plan-execute-demo에 도구를 연결해도 조용히 무시됐던 함정(당시). 202가 plan_execute의 도구 소비를
구현해 그 사례는 해소됐지만, **구조는 그대로**다: 편집 폼이 커스텀 impl을 "직접형 취급"해 도구·문서·
기억 피커를 전부 노출하고, impl이 안 읽어도 아무 표시가 없다. 현재 실함정=route(도구·문서 무시),
그리고 앞으로 만들 모든 impl.

## 설계 (매니페스트 자기선언 — 기존 accepts_overrides/supports_hil과 같은 축)

### A. AgentManifest.consumes (agent 패키지)
- `consumes: tuple[str, ...] | None = None` — 이 impl이 읽는 설정 표면 선언.
  어휘: `"mcps" | "vectorTables" | "memories" | "capabilities" | "artifactSpec"`.
- **None(미선언) = 폼 전부 노출(현행 그대로, 무회귀)** — 기본을 숨김으로 하면 선언 깜빡한 impl의
  표면이 거짓 소멸(더 나쁜 함정). 선언한 impl만 정확 게이트.
- 각 impl 선언(실소비 실측 기준): DefaultUiAgent=("mcps","vectorTables","memories") ·
  plan_execute=동일(202 이후 ctx.tools=mcps+rag, persona=회상) · route=("memories",) ·
  orchestrate=("capabilities","memories") · artifact=("artifactSpec",).

### B. impls 메타 노출 (api)
- `GET /agent-impls`: `list[str]` → `list[{key, consumes}]`(consumes None=null). FE 호출부 동기 수정.

### C. 폼 게이트 (AgentForm)
- impl 선택 시 consumes로 직접형 그룹(도구/문서/기억) **필터**: 선언에 없는 표면은 피커에서 숨김.
- **저장값 경고**: 숨긴 표면에 기존 연결이 남아 있으면 안내 — "이 실행 방식은 도구를 사용하지
  않습니다 — 저장된 연결 N개는 무시됩니다."(연결은 보존 — 지우지 않음, impl 되돌리면 부활).
- 조율형·산출물형의 기존 분기(108/190)는 유지 — consumes는 그 일반화(커스텀 임의 impl까지).

## 검증
1. 단위(agent): 각 impl manifest.consumes 값 · 미선언 None.
2. API: /agent-impls 응답에 consumes 포함.
3. e2e(폼): impl=route 선택 → 도구/문서 피커 숨김+기억만 노출, 기존 mcps 저장된 에이전트에 route
   선택 시 "무시됩니다 N개" 경고 · impl=plan_execute → 전부 노출(무회귀) · 직접 응답 무회귀.
4. tsc0 · ui-audit 스모크.

## 검증 중 부수 발견·수리 (2026-07-07)
- **모바일 내비 잠김**: 기본 뷰(agents)를 첫 클릭 시 antd Menu `onSelect`가 **이미 선택된 항목
  재클릭에 미발화** → 드로어 안 닫힘 → mask가 이후 감사 4건 연쇄 차단. onClick으로 교체(항상 발화).
- **감사 공허 초록**: overlays 하네스가 NAV 실패를 종료코드에 미반영 — 열지 못한 표면이 "통과"로
  집계되던 구멍. exit code에 navFails 포함.

## RBAC 경계
- 비트리거: 표시 게이트만. 저장값 불변(연결 보존), 런타임 무변경.

## 경계
- 런타임 강제(미소비 표면 저장 거부)는 OUT — 표시 정직화까지(저장 보존이 되돌림에 안전).
- 089 적합성에 consumes 검증 rung 추가는 OUT(선언은 자율 — 폼 무회귀가 기본값 안전을 담보).
