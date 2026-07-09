# 스펙 259 — 다단계(노드) 노코드 에이전트: 일렬 파이프라인 (사용자 지시)

## 배경 (2026-07-09, 사용자 요청)

기존 노코드 에이전트는 "한 덩어리"(단일 모델·페르소나·도구). 사용자는 **각 노드를 직접 정의**하는
에이전트를 원한다 — 노드마다 **프롬프트·실행 모델·참고 도구**를 고르고, 노드는 UI에서 추가.
사용자 관찰: "에이전트 설정이 노드 설정으로 N개 들어가는 것 같다"(정확). 토폴로지는 **일렬**로 확정
(조건 분기는 추후 — "여러 방식으로 구현 가능").

## 왜 가능한가 — 기존 패턴의 확장 (신규 발명 최소)

스펙 190(노코드 산출물형)이 이미 증명한 **설정 주도 신뢰 impl** 패턴 그대로다:
- 190: `config.artifactSpec`(폼 명세) → `ConfigDrivenArtifactAgent`가 읽어 폼 실행.
- 259: `config.nodes`(노드 명세 N개) → 새 신뢰 impl이 읽어 **일렬 그래프**를 만들어 실행.

**노드는 데이터**(프롬프트 글자·모델 이름·도구 id)이고 해석 엔진은 **고정 신뢰 코드**다 → eval/import
경로 없음(085 §보안경계 보존). 099에서 접은 "시각 그래프 빌더"의 위험(사용자 문자열=코드)이 여기엔
없다. 임의 토폴로지도 아니다(일렬 고정).

## 설계

### 설정 표면 — `config.nodes`
```json
"nodes": [
  {"name": "분석", "prompt": "…이 노드의 역할…", "model": "<모델 이름>", "tools": ["mcp:server/tool", "rag:col"]},
  {"name": "작성", "prompt": "…", "model": "<모델 이름>", "tools": []}
]
```
- 각 노드 = **작은 에이전트 설정**(프롬프트+모델+도구 부분집합). 순서가 실행 순서.
- `tools`는 **에이전트 capabilities의 부분집합**(자유 문자열 아님) — RBAC 경계 보존(아래).

### 신규 신뢰 impl — `LinearPipelineAgent` (NAME=`pipeline`)
- `flows/pipeline.py`에 `CustomAgent` 구현. `build_graph(ctx)`가 `ctx.impl_config["nodes"]`를 읽어
  **일렬 LangGraph**(node1→node2→…→END)를 조립. 각 노드 = call_model 스텝(자기 모델+프롬프트+도구).
- **주입만 읽는다**(085 U2): 노드 모델은 플랫폼이 미리 해석해 주입(아래), 도구는 `ctx.tools`에서 이름으로
  필터. 엔진은 DB·레지스트리 미접촉(순수). eval 0.
- 데이터 흐름: 누적 메시지 상태 — 각 노드가 출력을 메시지에 append, 다음 노드가 누적 맥락을 봄.
  **마지막 노드 출력 = 에이전트 응답.** 플레이그라운드 추적에 노드 이름별 실 노드열이 뜬다(합성 아님).
- `describe()`: `consumes=["nodes","memories"]`(206 자기선언), `supports_hil`=노드가 승인 도구를 바인딩할
  수 있으면 True(정직).

### 핵심 관문 — 노드별 모델 해석 (플랫폼 층)
`AgentBuildContext.model_cfg`는 **단일**이다. 노드별 모델은 build_graph가 DB를 못 보므로(085 U2)
**플랫폼이 미리 해석**해야 한다:
- `_load_context`(또는 헬퍼)가 impl이 `nodes`를 consume하면, 각 노드 `model` 이름을 기존 조회
  (`ModelConfig.name==name, kind=="chat"` → base_url/api_key/model_id/params, chat.py:212-245 재사용)로
  해석해 **노드에 resolved model_cfg를 심어** `impl_config`로 넘긴다. 노드가 모델 미지정이면 에이전트
  기본 `model_cfg`로 폴백.
- 엔진은 `node["model_cfg"]`를 그대로 써 모델 생성(이름→cfg 룩업 없음 = 순수 유지).

### 도구 부분집합 — RBAC 경계 보존
- 노드 `tools`는 **에이전트 capabilities에서 고른 부분집합**. 엔진은 `ctx.tools`(이미 RBAC·브로커로
  스코프된 해석 도구)에서 노드가 지정한 것만 바인딩. `ctx.tools`에 없는 이름은 무시(deny-by-default)
  → 노드가 에이전트 권한을 넘는 도구를 부를 수 없다(새 권한 표면 0, 190과 동일).

### 에이전트 레벨 model/persona의 역할 (사용자 결정 — 확정)
노드마다 모델·프롬프트가 있으므로:
- **`persona`(에이전트 레벨) 제거** — 노드형엔 공통 페르소나 없음. **각 노드가 자기 프롬프트를 직접
  작성**한다. 단, **등록된 페르소나에서 가져오기**는 기능으로 제공(노드 프롬프트 편집기에서 등록
  페르소나를 골라 그 본문을 편집 가능한 텍스트로 불러옴 — `GET /personas` 목록·본문 활용).
- **`model`(에이전트 레벨)** 은 사용자 대면 필드 아님 — 각 노드가 자기 모델을 고른다. 플랫폼은 메모리/
  mem0용으로 기본 chat 모델(is_default)을 `ctx.model_cfg`로 계속 해석(실행은 노드별 모델). 노드가 모델
  미지정이면 그 기본 chat 모델로 폴백.

### UI — AgentForm 종류 분기 + NodeListEditor (종류 이름 = "노드형", 사용자 결정)
- AgentForm "종류"에 새 항목 **"노드형"**. 190의 "산출물형" 분기와 동형.
- `NodeListEditor`: 노드 추가/삭제/순서변경, 노드별 = 이름·프롬프트(TextArea + **"등록 페르소나에서
  가져오기" 헬퍼**: 등록 페르소나 골라 본문을 편집칸에 로드)·모델(Select)·도구 피커(087/106
  capabilities 피커 재사용 — 에이전트가 배선한 도구에서 고름).
- 설정 왕복 3지점(AgentConfig + AgentOut + serializer, 190과 동일 — 얕은 검증기로 nodes 정규화).
- **206 게이트(사용자 동의)**: 이 impl은 `nodes`를 consume → 폼이 노드 편집기를 노출하고, **에이전트-레벨
  페르소나·모델·도구 그룹은 숨긴다**(노드가 전부 정하므로). 데이터 보존(impl 되돌리면 부활, 206 규약).

## 사용자 결정 (확정, 2026-07-09)
1. **에이전트 레벨 페르소나 제거** — 노드마다 직접 작성 + 등록 페르소나 가져오기 기능. 에이전트 레벨
   모델은 사용자 필드 아님(플랫폼 기본 chat만, 노드 폴백).
2. **폼에서 에이전트-레벨 도구/모델/페르소나 그룹 숨김**(동의).
3. **종류 이름 = "노드형"**.

## 검증 (사다리 3런)
- **단위** `verify_259_pipeline.py`: impl 등록·`build_graph(mock ctx)` 컴파일·`get_graph().nodes`가
  선언 노드 이름집합과 일치(순서·개수)·노드별 model_cfg/도구 부분집합 바인딩·`describe()` 정직·
  `list_agent_impls()`에 `pipeline`·설정 왕복 보존.
- **통합**(in-process ASGI + 실 그래프): 2~3노드 파이프라인을 API로 저작 → chat SSE → 토큰 +
  **노드 이름별 실 타임라인 순서대로**(각 노드가 자기 모델로). 생성 정리.
- **무회귀**: 085·089·188·190·206 + tsc 0.
- **적대(codex)**: 엔진이 주입 ctx 외를 읽나·노드 모델 해석이 타 유저 모델/키를 새게 하나·노드 도구가
  에이전트 capabilities를 넘나(부분집합 강제)·eval 경로 여나 — 여집합 검토.

## 경계 (기록)
- 일렬 고정(분기 없음) — 추후 조건 분기는 별 스펙(edge+조건 데이터, 여전히 설정 주도).
- 노드 도구 ⊆ 에이전트 capabilities(권한 상승 0). 노드 모델 ⊆ 등록 모델(이름 미존재→기본 폴백).
- 비영속·무오염 등 실행 계약은 기존 ui 에이전트와 동일(새 실행 경로 아님 — 같은 chat.py 로컬 경로).

## 결과 (구현·검증, 2026-07-09)

**백엔드**: `agent/flows/pipeline.py`(`LinearPipelineAgent`, 신뢰 impl `pipeline`) + runtime 등록 +
chat.py `_resolve_node_models`(노드 model 이름→cfg 미리 해석, 플랫폼이 주입) + 2개 impl_config 주입
지점 + schemas(`AgentConfig.nodes`+검증자, `AgentOut.nodes`) + serializers. 노드 model_cfg/api_key는
런타임 ctx에만 실리고 `AgentOut.nodes`엔 model **이름**만(비밀 무유출).

**프론트**: `NodeListEditor.tsx`(190 `ArtifactSpecEditor` 관용구 계승 — 카드+add/remove+`pipelineValid`)
+ AgentForm 위저드(239) 통합: 종류 "노드형" 추가, 정체성 단계서 모델/페르소나 숨김+안내, "하는 일"
단계서 노드 편집기, 요약에 "처리 단계" 행, `finalizeForm`이 저장 직전 **도구 풀(mcps/vectorTables)을
노드 도구 합집합에서 파생**(에이전트-레벨 도구 UI 없음). AgentsView 왕복 3지점(configOf·save·reload).

**노드 카드 UX**(노하우 적용): 단계 번호 배지 + 이름 + ↑↓ 순서이동 + 삭제 · 프롬프트(TextArea, 라벨
줄에 "등록 페르소나에서 가져오기" — learning 078 세로 스택) · 모델(자동 첫 옵션)+도구(멀티, 선택) ·
노드 사이 ↓ 연결선으로 일렬 흐름 시각화(beauty=trust).

**검증**:
- **단위**: `verify_259_pipeline.py` 15/15 (전 턴). 무회귀 085·089·190 통과 + **tsc 0**.
- **실인프라 통합**(브라우저 왕복, `tests/browser/shot-pipeline-259.mjs` 11체크 ALL GREEN): 실 admin
  로그인→종류 노드형(모델/페르소나 숨김 확인)→빈 파이프라인 게이트(다음 비활성)→노드 저작(도구·페르소나
  불러오기)→요약→생성→**브라우저 세션으로 `GET /api/agents` 재조회**: `impl=pipeline`·`nodes` 2개 보존
  (프롬프트·모델)·`conformance=conforming`·**도구 파생**(노드 도구 `add`→`mcps=["calc-tools"]`)·페르소나
  불러오기가 노드 프롬프트 채움(결정 #1). 이 rung이 serializer 왕복·conformance 파생·풀 파생을 실측
  (단위가 못 보는 요청간 글루, learning 040).
  - antd6 도구/페르소나 셀렉터가 개명된 `.ant-select-selection-placeholder`로 2회 미스→**getByText로 교정**
    (learning 080 재확인).
- **적대(codex)**: 커밋 후 권장(이 세션 리듬 — 커밋→코덱스). 추가적 additive 경로라 파괴/인가 경계 아님.

**잔여(기록)**: (1) execute e2e(활성화+chat로 노드 순서 실행)는 미실행 — draft만 생성해 확인. 다음
확장에서 활성화+chat 타임라인. (2) `describe().consumes`에 `memories` 선언되나 노드 프롬프트가 회상을
안 실음(에이전트 persona 경로를 pipeline이 무시) — 노드별 메모리는 미래 확장, v1은 memories 사실상 미사용.
(3) RAG는 `search_documents` 단일 도구라 노드별 컬렉션 스코핑 불가 — "문서 검색" 쓰면 vectorTables=전체
컬렉션 파생(문서화된 v1 한계).
