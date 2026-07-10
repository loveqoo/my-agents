# 276 — 직접형 에이전트 도구 단위 배선 (서버 단위 → 도구 단위)

> 사용자 결정. 배경: "도구 1개가 3기능일 때 각각 고르면 그것만 호출되나?" → 노드형=예(도구 단위
> bind+ToolNode), 직접형=아니오(서버 단위). "원격이라 어쩔 수 없다"는 오해도 해소 — MCP는 클라이언트가
> tools/list에서 노출을 고르는 구조라 **서버 단위는 설정 모델의 선택이었지 기술 제약이 아님**
> (enabled_tools·노드형이 증거). 직접형도 도구 단위로 정렬한다.

## 설계 (측정 근거 포함)

**저장**: `AgentConfig.tools: list[str]` 신설 — 노드와 같은 런타임명(`server__tool`, safeToolName).
`mcps`는 **서버 합집합 파생으로 유지**(파이프라인 268 P1 선례) — 이유: 서버 로드(`_load_context`
name.in_), MCP 삭제 가드(093 `_config_has`), 카탈로그·조율형이 전부 mcps를 소비하므로 시맨틱 변경은
파급이 큼. pydantic AgentConfig에 필드 필수(model_dump 드롭 방지 — learning 101 동형).

**런타임 시맨틱(서버별)**: `build_mcp_tools(..., selected_tools)` —
- 선택 목록에 **그 서버의 항목이 하나라도 있으면** 그 항목만 노출.
- **그 서버의 항목이 없으면 전체 노출**. 이 폴백이 세 무회귀를 한 번에: ①구저장(tools 자체가 빈
  목록)=지금과 동일, ②오버라이드로 서버 통째 추가, ③카탈로그에 도구 목록이 없는 서버의 보존.
- 서버별 판정은 순수 함수 `selected_for_server`로 분리(연결 없이 단위 테스트).
- 노드형 무회귀: 노드는 ctx.tools 풀에서 노드별 재해석(265) — 파이프라인 에이전트는 agent-level
  tools를 저장하지 않으므로 풀은 전체(변화 없음).

**오버라이드(세션)**: allowed 키 + trace 키에 `tools` 추가. OverridePanel 도구 피커를 서버 단위 →
도구 단위 항목으로. 적용 시 `mcps`는 tools의 서버 합집합으로 파생 전송(서버 로드가 mcps 기준이므로).

**폼(직접형)**:
- "이 대화에서 쓸 것" 도구 그룹 항목 = 도구 단위(`서버 · 도구`, 노드 옵션과 동일 어휘).
- **하이드레이션(핵심 무손실)**: 구저장(tools 빈값+mcps 있음) 편집 로드 시 카탈로그에서 그 서버들의
  전체 도구로 **확장**해 채운다 — 안 하면 편집 후 저장에서 배선이 통째 유실(sync-wholesale-replace
  함정). 카탈로그에 도구 목록 없는 서버는 확장 불가 → 서버명을 보존 셋에 담아 mcps 파생에 합류
  (런타임 폴백=전체라 동작 보존).
- 저장 파생: `mcps = union(tools의 서버) ∪ 보존 셋`.
- **승인 오버라이드 목록 정합**(사용자 관찰 후속): 직접형=선택 도구만, 노드형=노드 합집합 도구만
  (지금은 배선 서버의 전체 도구 — 노드형에서 과잉). 조율형은 서버 위임이라 전체 유지.

## 완료 조건 (측정 가능)
1. 단위: `selected_for_server` — 항목 있음→그것만 / 없음→None(전체) / 타 서버 항목 무영향.
2. e2e 저장 왕복: 직접형 폼에서 calc-tools의 도구 1개만 체크→저장→`config.tools=[그 1개]`,
   `mcps=["calc-tools"]` 파생.
3. **e2e 런타임(핵심)**: 도구 1개만 배선한 에이전트와 mock-llm 대화 — 선택 도구는 호출됨(trace
   calls), **비선택 형제 도구는 호출 안 됨**(negative — 모델에 노출 자체가 안 됨).
4. 구저장 무회귀: tools 없는 기존 에이전트 대화 시 서버 전체 도구 노출(기존 268 도구 루프 e2e GREEN).
5. 하이드레이션: 구저장 편집 열람 시 피커에 서버 전체 도구 체크됨 → 그대로 저장해도 배선 불변.
6. 승인 오버라이드 목록 — 직접형에서 선택 도구만 나열.
7. tsc 0 + 272/273/274/275 무회귀.

## 무회귀·경계
- 조율형(capabilities `mcp:server`)·노드형은 무변경. 삭제 가드·A2A·eval은 mcps 파생 유지로 무변경.
- API 직접 저작(curl)이 tools만 넣고 mcps를 안 넣으면: 서버 로드가 mcps 기준이라 tools는 무효과
  (문서화 — mcps가 서버 배선의 진실원, tools는 그 위의 필터).
- 검증 사다리: 단위(순수 함수)+실모델/mock e2e(positive+negative)+형제 회귀+codex 적대(권한 인접).

### 검증 결과
- **단위 verify_276_tool_wiring.py 10/10**(폴백·서버별 분할·대시 접두 비혼동·라운드트립 보존).
- **e2e verify-276-tool-wiring.mjs 15/15 ALL GREEN** — ① UI 저장 왕복(도구 단위 피커·승인 목록 선택
  도구만·config.tools/mcps 파생) ② positive(echo 배선→echo 호출) **③ negative(비선택 web_search
  호출 없음 — 노출 차단)** ④ control(구저장 동형은 web_search 호출됨 = ③이 필터 때문임을 대조 증명)
  **④b pipeline 게이트**(agent-level tools 있어도 노드 web_search 호출됨 = 풀 미축소) ⑤ 하이드레이션.
- **형제 회귀**: 272·273·274·275·123·268 실모델 파이프라인 ALL GREEN. tsc 0.
- **codex 적대(4 발견) 판정**:
  - **Low(pipeline config.tools가 노드 풀 조용히 축소) = 수정함**: curl 직접 저작으로 impl=pipeline +
    config.tools 저장 시 노드 도구가 미바인딩. 백엔드에서 impl 게이트(pipeline·orchestrate 계열은
    tool_names=[]=전체 폴백) — UI finalize 규칙(pipeline은 tools:[])을 백엔드에서도 강제
    ([[gate-on-intent-value-not-mutable-baseline]] 패턴). e2e ④b가 봉합 실증.
  - **High(overrides.tools=[]로 전체 폴백 복귀=저장 필터 제거) = 정직 경계(OUT)**: 오버라이드는
    **세션 한정 자기 덮어쓰기**(스펙 025)이고 mcps 오버라이드로도 서버 확대가 원래 가능했다(276이 연
    구멍 아님). 승인 게이트(177)는 재노출 도구에도 유지(codex도 확인) — 안전 위반 아님. UI는 항상
    tools를 채워 보내(하이드레이션) tools=[] 폴백은 curl 공격에만. [[complement-attack-can-be-honest-boundary]].
  - **Medium(_safe_name 충돌: `read.secret`·`read_secret`가 같은 런타임명) = OUT(기존 클래스)**: 265
    safeToolName 도입부터의 성질(276 신규 아님)·노드형 필터도 동일. 도달=한 서버가 sanitize 충돌하는
    두 도구명 노출(비정상)·승인 유지. 272 예약 이름공간 불변식과 같은 판정([[hand-authored-migration-ids-collide-silently]] 아님, 272 주석 참조).
  - **Low/Medium(다중 서버 폴백=전역 allowlist 아님) = 의도(문서화)**: 서버별 독립 필터가 설계
    (selected_for_server 서버 인자). codex도 "의도된 무회귀" 인정. tools는 "배선 서버 위의 서버별
    노출 필터"이지 전역 화이트리스트가 아님 — mcps가 서버 배선의 진실원.
- **codex 재리뷰 불필요 판정 근거**: 유일한 코드 결함(pipeline)은 수정+e2e 실증, 나머지는 도달 불가
  또는 기존 오버라이드/naming 모델의 성질. 완화 방향(승인 우회) 없음이 codex·본 검증 양쪽서 확인.
