# 287 — 노드형 에이전트의 플레이그라운드 오버라이드 (구조 불변·필드만)

> 사용자 결정: 노드형(pipeline)도 오버라이드 지원. 단 **노드 추가/삭제는 테스트 범위 밖** —
> 오버라이드는 "이 에이전트 그대로, 설정만 바꿔 테스트"가 목적이라 구조 변경은 다른 에이전트를
> 테스트하는 것. 구조 불변은 UI 숨김이 아니라 **서버가 강제**(클라이언트 신뢰 금지 — systemPrompt
> 빈값 가드와 같은 원칙).

## 배경 (실측)
- 오버라이드는 chat.py `_load_context`가 화이트리스트 키만 `cfg`에 덮는 구조(025/276). 노드 명세는
  그 **직후** `ctx["nodes"] = cfg.get("nodes")`로 흐름 — nodes를 받으면 기존 파이프 그대로 반영됨.
- 안전: 노드 모델=레지스트리 이름 해석만(012 불변식), 노드 도구=바인딩 부분집합만 유효(밖 이름
  무시=권한 상승 0), 승인 게이트=실행 시점(무관), 세션 한정(저장본 불변).
- 현 UI 어긋남: OverridePanel이 직접형/조율형 분기만 있어 노드형에 직접형 표면(도구 트리·장기
  기억)이 노출 — 런타임 미사용(노드 소유)이라 108/124 계열 오해 표면.
- 노드형 풀 파생: 폼 저장 시 mcps·vectorTables·memories를 노드 도구·기억 **합집합에서 파생**
  (finalize). 오버라이드도 같은 파생을 보내야 노드 변경이 실효. `vectorTables`는 allowed에 없어
  추가 필요(RAG 사용=공용 정책 211 — 완화 아님).

## 변경

### 백엔드 (chat.py)
1. **노드 오버라이드 merge(구조 불변 강제)** — 순수 함수 `_merge_node_overrides(saved, ov)`:
   - 길이 같을 때만 적용: 인덱스별로 **필드 화이트리스트만** 저장 노드 위에 덮음
     `{prompt, model, tools, historyDepth, memories, memoryQuery, context, format, fields}`
     (`name` 제외 — 구조 식별자는 저장본 유지). 반환 `(nodes, "applied")`.
   - 길이 불일치/형식 오류 → 저장 노드 그대로 + `"mismatch"` (조용한 드롭 금지 — 125 표면화).
   - `_load_context`에서 overrides.nodes 있으면 호출, 상태를 `ctx["overrides_nodes_status"]`에.
2. **allowed에 `vectorTables` 추가**(노드 문서 오버라이드 실효 축 — RAG 읽기, 211 사용=공용).
3. **트레이스(134)**: `_overrides_trace(overrides, nodes_status=None)` — nodes는
   `{"count": N, "status": applied|mismatch}` 요약(프롬프트 전문 미기록), vectorTables 키 추가.
   pending/최종 트레이스 조립부 3곳에 status 전달.

### 프론트
4. **풀 파생 단일 출처**: AgentForm finalize의 파생 로직을 `derivePipelinePool(nodes, mcpItems,
   collections)`로 export, finalize·오버라이드 페이로드 둘 다 사용(261 교훈 — 사본 금지).
5. **Overrides에 `nodes?: PipelineNode[]`** — overrideDefaults가 저장 노드 깊은 복사,
   overridePayload가 변경 시 `nodes` + 파생 풀(mcps/vectorTables/memories) 동봉.
6. **NodeListEditor `fixedStructure` prop** — 추가/삭제/이동 버튼 숨김, 이름은 읽기 전용 표시
   (열림 상태에서도 Input 대신 텍스트). 필드 편집(프롬프트·모델·기억·도구·문서·받기·형식)은 동일.
7. **OverridePanel 노드형 분기**(108: kind별 표면): Steps=`노드`/`세부`.
   - 1단계: 세션 한정 안내 + `NodeListEditor fixedStructure`(폼과 같은 공용 에디터 — 273 원칙).
   - 2단계: 단기 기억(노드 상속 원천)·temperature만. 직접형 표면(에이전트 모델·프롬프트·도구
     트리·장기 기억)은 숨김 — 노드형 런타임 미사용.

## 완료 조건 (측정 가능)
1. [단위] merge: 필드만 덮음·name 보존·화이트리스트 밖 키 무시·길이 불일치=mismatch+저장본.
2. [통합, 실 DB+라우트 직호출] 노드형 에이전트: (a) overrides.nodes로 노드 도구를 빼면 mock-llm
   도구 호출이 사라짐(효과 실측), (b) trace.overrides.nodes={count,status:applied},
   (c) 길이 다른 nodes → status:mismatch + 저장 노드로 실행(응답 무변).
3. [e2e] 노드형 오버라이드 드로어: 노드 에디터 노출·추가/삭제/이동 부재·이름 읽기전용·직접형
   표면(도구 트리 등) 부재·적용 → '적용 중'. 직접형/조율형 드로어 무회귀.
4. tsc 0 + codex 적대(오버라이드=인가 인접 — merge 화이트리스트·구조 게이트).

### 검증 결과
- **verify_287_node_overrides.py 25/25 ALL PASS** (사다리 3런 중 U+H):
  - [U 14] merge 시맨틱(필드만·name 보존·화이트리스트 밖 무시·저장본 원본 불변·길이/형식
    불일치=mismatch+저장본), 트레이스 요약(count+status만·프롬프트 전문 미기록·mismatch도 기록).
  - [H 11] in-process ASGI+실 DB+mock-llm: **효과 실측** — 노드 도구 제거 오버라이드 →
    trace["mcp"] echo 호출 1→0(H2), 구조 불일치 → 저장 노드로 실행(echo 유지)+mismatch 표면화(H3),
    name 오버라이드 → 실행 그래프 노드명 저장본 유지(H4), 비노드형+nodes → 무해·mismatch(H5),
    historyDepth 비정수 → 500 없이 실행(H6, codex Low 봉합).
- **verify-287-node-override-drawer.mjs 17/17 ALL GREEN**(e2e): Steps=노드/세부, 노드 카드 2,
  직접형 표면(시스템 프롬프트·도구 트리·장기 기억·Temperature) 부재, 추가/삭제/이동/이름 Input
  부재(필드 편집은 가능), 적용 → POST /chat body.overrides.nodes(길이 2·수정 프롬프트·타 노드
  저장값)+파생 풀 mcps 배선.
- **verify-287-e2e-effect.mjs 5/5 ALL GREEN**(브라우저 종단 한 바퀴 — 사용자 질문 "테스트
  해보셨나요?"로 추가): UI에서 노드 도구 체크 해제 → 적용 → **응답** trace에서 echo 호출 1→0 +
  overrides.nodes=applied. 요청 payload 캡처가 아니라 응답 효과 단언(UI 검증은 기능적으로).
  함정 1건: ToolTree는 선택 도구가 있으면 defaultActiveKey로 **기본 펼침** — 무조건 헤더를
  클릭하면 열린 걸 닫는다(트리 가시성 조건부 클릭으로 수리).
- 형제 회귀: verify-273(직접형 드로어)·275(노드 아코디언 폼)·278(트리)·279(폼 흐름) ALL GREEN.
  tsc 0.
- **codex 적대(오버라이드=인가 인접)**: High 0. 판정 기록 —
  - Medium "노드 tools 오버라이드가 저장 바인딩 의도를 넓힘": **기존 오버라이드 시맨틱과 동등**
    (직접형 overrides.mcps/tools가 025/276부터 같은 표면). 승인 게이트·MCP enabled_tools는 codex도
    불변 확인 — 정직 경계로 문서화(수용).
  - Medium/정책의존 "vectorTables=임의 컬렉션 읽기": 컬렉션은 211 "사용=공용" 정책이라 현재 정당.
    **컬렉션에 접근 제어를 도입하면 이 allowed 키를 재검토할 것**(정책 의존성 명시).
  - Low "타입/크기 검증": historyDepth 비정수 → TypeError 500(287 이전부터, allowed 키라 도달
    가능) — 정수화 실패 시 저장값 폴백으로 봉합+H6 회귀. toolPolicy 완화·저장본 오염·비밀 누출은
    도달 불가 판정.
