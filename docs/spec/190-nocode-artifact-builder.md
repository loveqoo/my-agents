# 190 — 노코드 산출물형 에이전트 빌더 (P1)

## 배경·의도
스펙 188이 산출물형 에이전트의 **코드 버전**(개발자가 `produce()` 저작)을 만들었다. 사용자 방향:
**노코드 버전** — 개발자가 아닌 사람이 어드민에서 "무엇을 모아 어디로 보낼지"만 정의하면 되게. 원칙:
"이 서비스를 모르는 사람도 이해"(가이드 189와 같은 눈높이). sink 범위는 **브라우저 콜백만**(사용자
결정 2026-07-06 — 외부 API POST는 SSRF·허용호스트 별도 사다리라 P2).

## 설계 (뼈대 재활용 — 둘째·셋째 구현 누수0 규율, 회고 173)
**내부 = 범용 에이전트 하나가 "설정"을 읽어 뼈대를 돈다.** targeting(동적) 같은 자유 로직은 코드 버전 유지.

- **`ConfigDrivenArtifactAgent`**(NAME=`artifact_form`) — flows/artifact.py. produce가 하드코딩
  로직이 아니라 **에이전트별 필드 명세를 읽어** `ctx.form(fields)` → `Artifact(kind, data=values)`.
  뼈대(멀티턴·폼·검증·이중입력·emit) 무변경으로 붙는다(누수0 측정 대상).
- **설정 통로(뼈대 배선, 추가 필드 2개 — 기존 에이전트는 무시)**:
  - `AgentBuildContext.impl_config: dict | None` — 플랫폼이 에이전트 config에서 뽑아 주입.
  - `ProduceContext.config: dict | None` — 뼈대 produce_node가 `ctx.impl_config`를 넣어줌.
  - `ConfigDrivenArtifactAgent.produce`는 `ctx.config`에서 필드 명세를 읽는다.
  - chat.py: `AgentBuildContext(impl_config=cfg.get("artifactSpec"))` (in-process 로컬 경로만).
- **저장 형태 `config.artifactSpec`**(스펙 188 필드 dict 재사용):
  ```json
  {"kind": "form-result",
   "fields": [{"key": "...", "label": "...", "candidates": ["..."], "required": true}]}
  ```
  후보 있으면 SelectBox(enum), 없으면 자유 입력. `validate_form_values`가 후보 게이트(P2-1 하드닝 포함).
- **sink = 브라우저 콜백** — 새 코드 0. 완성 artifact가 기존 `{artifact:...}` 프레임으로 흘러
  admin ArtifactCard/host JS 콜백에 닿는다(스펙 188 P4 그대로).

## 화면 (AgentForm)
- "에이전트 종류"에 **산출물형** 추가(현재 직접 응답/조율형 → 셋). 고르면 `impl='artifact_form'`.
- 고르면 **필드 편집기** 노출(하는 일 pickers 대신): 행 추가/삭제, 각 행 = 라벨 + 유형(자유입력/선택)
  + 후보(선택일 때 태그 입력). `form.artifactSpec.fields`로 저장. 최소 1개 필드 필수(저장 검증).
- sink 안내: "결과는 임베드된 페이지의 JS 콜백으로 전달됩니다"(P1 고정).

## 검증(사다리)
- **단위/그래프**: `ConfigDrivenArtifactAgent`가 spec을 읽어 form interrupt→제출→artifact 커밋(spec
  없거나 빈 fields면 명시적 처리). `impl_config→config` 배선 무회귀(기존 데모 config=None).
- **e2e**: 어드민에서 산출물형 에이전트 생성(필드 2개, 하나는 후보)→플레이그라운드→폼→제출→artifact
  카드. 이중입력(텍스트 보완)도 1케이스.
- **무회귀**: verify_188(뼈대·데모)·admin tsc 0·scenario.

## 실행 결과 — 완료·검증 (2026-07-06)
- **백엔드**: `ConfigDrivenArtifactAgent`(NAME=artifact_form) + `normalize_artifact_fields`(순수·방어) —
  flows/artifact.py. 설정 통로 = `AgentBuildContext.impl_config`(신규) → 뼈대 produce_node가
  `ProduceContext.config`(신규)에 주입 → produce가 `ctx.config`에서 명세를 읽음. chat.py는
  `ctx["artifact_spec"]=cfg.get("artifactSpec")` → `AgentBuildContext(impl_config=…)`. **뼈대(@final
  build_graph/produce_node) 무변경 = 셋째 구현 누수0 확인**. `register_agent("artifact_form", …)`.
- **스키마 왕복**: `AgentConfig.artifactSpec`(+얕은 검증 field_validator: fields=배열·각 key:str·≤100)
  + `AgentOut.artifactSpec` + `serializers.agent_to_out`. 저장→재로드 무손실(learning 101 동형 봉인).
- **프런트**: `ArtifactSpecEditor.tsx`(신규, 스펙 185 분해 패턴) — 항목 행(라벨·결과키·유형[자유/선택]·
  후보 태그·필수) 추가/삭제, `artifactSpecValid`로 저장 게이트. AgentForm "종류"에 **산출물형**
  (impl=artifact_form) 추가, 고르면 "하는 일" 대신 편집기 노출. AgentsView save/configOf/편집오픈 3곳
  왕복 배선. sink 안내 문구 고정("JS 콜백으로 전달").
- **검증 사다리 3단**: `verify_190_nocode_artifact.py` 단위(N normalize·C config주도 폼·E 빈명세·D
  이중입력) ALL PASS · `verify-nocode-artifact-190.mjs` e2e(**U 폼으로 저작→P API 왕복 보존→R
  플레이그라운드 실행→폼→제출→artifact 카드**) ALL PASS · 무회귀(verify_188 뼈대·verify_041 HIL·
  admin tsc 0). 실행 화면 시각 확인(nocode-190-artifact.png: `{"purchase":"최근 한 달"}`+콜백 안내).
- **RBAC**: 새 쓰기 입구 0(artifactSpec은 기존 에이전트 CRUD의 owner 스코프 config, sink=기존 브라우저
  프레임). 얕은 검증기가 형태 강제, 런타임 normalize가 값 방어(후보 게이트 P2-1 동형).

## 경계(정직·P2 이후)
- sink는 브라우저 콜백만. 외부 API POST(허용호스트·SSRF 검토)는 P2.
- 필드 편집기는 평면 필드만(중첩·조건 분기 없음 — 그건 코드 버전). 동적 후보(RAG/도구서 가져오기)도
  코드 버전(targeting).
- artifactSpec은 에이전트 작성자(member+)가 저작 — 폼 명세라 신뢰 코드 아님, `validate_form_values`가
  런타임 방어. 저장 시 얕은 형태 검증(fields=list·각 key:str)만.
