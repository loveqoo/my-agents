# 261 — 노드 출력 형식 강제: 자유 텍스트 / JSON (스펙 259·260 확장)

## 배경
260에서 "깨끗이 받기"로 형식 고정 노드의 *입력*을 정제했다. 이제 그 노드의 *출력* 형식 자체를
**강제**한다(사용자 요청 #3, 2026-07-09): 노드가 JSON을 뱉게 하고, 파싱·검증해 하류가 깔끔한
구조를 받게. 260(입력 격리)과 직교 — 아무 노드나 형식 강제 가능(clean과 짝이면 순수 JSON 파이프).

## 설계
`config.nodes[].format` + `config.nodes[].fields`:
- **`format="text"`(기본)**: 자유 텍스트(259/260 기존, 무회귀).
- **`format="json"`**: 유효한 JSON 객체 하나를 강제. `fields`(문자열 키 목록, 선택)를 주면 그 키들의
  존재까지 검증. 비우면 "유효 JSON"만.

### 강제 방식 (best-effort, 정직한 폴백)
임의 OpenAI 호환 엔드포인트(mock 포함)라 네이티브 structured-output에 의존 못 함. 3중:
1. **프롬프트 지시**: JSON이면 시스템 프롬프트에 "최종 답변은 유효한 JSON 객체 하나로만(도구 호출은
   예외), 코드블록·설명 없이" + 키 목록을 덧붙임(모델이 첫 시도부터 JSON 지향).
2. **파싱·검증**: 노드의 **최종 응답**(tool_calls 없는 응답)에만 적용. 관대 추출(첫 `{`~마지막 `}`
   슬라이스→json.loads, 실패 시 전체) + 필수 키 존재 검사. 성공 → **정규화**(json.dumps ensure_ascii=
   False)로 내용 교체(하류가 깨끗한 JSON). 도구 루프 중간 응답(tool_calls 有)은 건드리지 않음.
3. **1회 보정 재요청**: 파싱 실패 시 unbound 모델에 "이 내용을 요청 JSON으로 변환해 JSON만 출력"
   1회 → 재파싱. 그래도 실패면 **원문 통과**(크래시 0·거짓 JSON 조작 안 함 — 정직).

## 구현 (입구 배선)
- **pipeline.py**: `_coerce_json(text, fields)`(순수 — 관대 추출·파싱·필수키 검사, obj|None) +
  `normalize_nodes`(format∈{text,json} 외→text·fields 문자열만) + `_make_step`(JSON이면 sys에 지시
  덧붙임·최종 응답에 강제·1회 보정은 unbound model).
- **_resolve_node_models**: `{**n}`이라 format/fields 자동 보존(수정 불요).
- **프론트**: `PipelineNode.format`·`.fields` + NodeListEditor "출력 형식" Select(자유 텍스트/JSON) +
  JSON일 때 "필수 키(선택)" 태그 입력. 저장/재로드 노드 통째라 자동 왕복.

## 검증 (사다리)
- **단위** `verify_261_output_format.py`: (1) `_coerce_json` 순수(코드펜스·전후 산문 감싼 JSON 추출·
  필수키 누락 None·비-JSON None), (2) normalize(format/fields 정규화·잡값→text), (3) JSON 노드 첫
  응답이 유효 JSON이면 정규화 통과(가짜 모델), (4) 첫 응답이 산문이면 1회 보정 후 JSON, (5) 보정도
  실패면 원문 통과(크래시 0), (6) text 노드 무회귀(형식 미개입).
- **무회귀**: verify_259 15/15·verify_260 10/10·tsc 0.
- **통합**(브라우저 왕복): 노드에 JSON+키 설정→생성→GET로 format/fields 보존.
- **적대(codex)**: #2에서 259+260+261 묶어 — 관대 추출이 인젝션/자원고갈 표면인가·보정 무한루프
  가능성·원문 폴백이 형식 계약 위반을 조용히 숨기나.

## 경계
- 강제는 best-effort(모델 미협조·mock이면 원문 폴백). "보장"이 아니라 "강제 시도+정직한 실패".
- 중첩 스키마·타입 검증(숫자/배열)은 이 스펙 밖(키 존재만). 필요 시 후속.

## 결과 (구현·검증, 2026-07-09)

**구현**: pipeline.py — `_coerce_json(text, fields)`(순수: 관대 추출·파싱·필수키 검사) + `normalize_nodes`
(format∈{text,json}·fields 문자열만) + `_make_step`(json이면 sys에 형식 지시 덧붙임 + `_finalize`가 최종
응답[tool_calls 없음]에만 강제: 파싱→실패 시 unbound 모델로 1회 보정→그래도 실패면 **원래 노드 응답**
통과[보정물 아님]). 프론트 — `PipelineNode.format`·`.fields` + NodeListEditor "출력 형식" Segmented +
JSON일 때 필수 키 태그 입력. `_resolve_node_models` `{**n}`·노드 통째 저장이라 자동 왕복.

**검증**:
- **단위** `verify_261_output_format.py` 14/14: U1 `_coerce_json`(코드펜스·전후 산문 추출·필수키 누락
  None·배열 None), U2 normalize, U3 유효 JSON 정규화 통과, U4 산문→1회 보정→JSON, **U5 보정 실패→원래
  응답 통과(크래시0)**, U6 text 무회귀. 가짜 모델 스크립트 응답으로 강제·보정 경로 결정적 검증.
- **무회귀**: verify_259 15/15·verify_260 10/10·tsc 0.
- **통합**(브라우저 왕복, shot 확장): 노드1 출력형식 JSON→생성→GET로 `nodes[0].format=json` 보존.

**정직한 결정(U5)**: 보정 실패 시 통과값은 **원래 노드 응답**(보정 시도물이 아님). 보정은 형식 변환
시도일 뿐, 노드의 진짜 답은 원문 — 조작된 보정물보다 원문 보존이 정직.

**경계**: best-effort(모델 미협조·mock이면 원문 폴백 — "보장" 아닌 "강제 시도+정직한 실패"). 중첩
스키마·타입 검증은 이 스펙 밖(키 존재만). 형식 어긋난 폴백을 소비층이 인지할 신호(예: 트레이스 플래그)는
후속 여지 — codex(#2)에서 "원문 폴백이 형식 계약 위반을 조용히 숨기나" 적대 검토 대상.
