# 260 — 노드별 맥락 모드: 이어받기 / 깨끗이 받기 (스펙 259 확장)

## 배경·문제
259 노드형은 노드들이 **하나의 누적 대화**를 공유한다(각 노드 = `[자기 시스템 프롬프트, *누적 messages]`
로 실행 → 응답을 messages에 append → 다음 노드가 누적 맥락을 봄). 이 "대화 이어가기"는 다듬기·이어쓰기
파이프라인엔 좋지만, **응답 형식을 고정한 노드**(예: "JSON으로만 답하라")엔 약점이다(사용자 지적, 2026-07-09):

- **입력 오염**: 형식 고정 노드가 앞의 자연어 대화·이전 시스템 프롬프트까지 다 보면 형식을 흐트러뜨리기 쉽다.
- **출력 오염**: 깔끔한 결과가 대본에 파묻혀 다음 노드로 넘어가면 하류도 잡음을 물려받는다.

사용자 직관: *"형식을 고정한 노드에선 쌓인 대화를 제거하는 방식이 필요하지 않을까?"* → 맞다.

## 설계: 노드마다 "맥락 모드" 토글 (전역 아님)
노드 카드에 스위치 하나(antd Segmented — 폴더 규칙: 모드=Segmented). `config.nodes[].context`:

- **`carry`(기본, "대화 이어가기")** — 지금까지 누적 대화 전체를 보고 자기 일을 함(259 기존 동작, 무회귀).
- **`clean`("깨끗이 받기")** — **격리 경계**. 첫 진입 시 쌓인 대화를 **전부 걷어내고**, 딱 **앞 노드
  결과만** 새 입력(HumanMessage)으로 받아 자기 일을 함. 이후 하류는 이 노드부터의 깨끗한 맥락만 봄.
  형식 고정(JSON 등) 노드에 적합. 연속된 clean 노드 = 순수 파이프.

전역 A/B/C(누적/파이프/템플릿) 대신 **노드별 토글**로: 대부분 노드는 이어받기, 형식 고정 노드만 깨끗이.
**템플릿 표현식(`{{...}}`)은 도입하지 않는다** — 이 토글이 "형식 고정+깨끗한 전달" 실수요를 덮는다.
표현식은 "여러 앞 노드를 섞어야" 하는 요구가 실제로 생기면 후속(별 스펙).

## 구현 (입구 배선 — learning 088)
- **pipeline.py `normalize_nodes`**: `context`를 읽어 정규화(`carry`/`clean` 외 값→`carry` 폴백). 순수.
- **pipeline.py `_make_step`/`_step`**: clean **첫 진입**이면(재진입=마지막이 ToolMessage로 판별) 기존
  messages를 `RemoveMessage`로 전부 제거 + 앞 결과 텍스트를 `HumanMessage`로 새로 심고 실행 →
  격리 working buffer 확보(도구 루프 재진입은 그 buffer 위에서 정상 동작, 재-오염 없음). carry는 259 그대로.
- **model 해석 통로**: `_resolve_node_models`는 `{**n, ...}`라 `context` 자동 보존(수정 불요).
- **프론트**: `PipelineNode.context?: 'carry'|'clean'`(mockData) + NodeListEditor Segmented 토글
  (기본 carry) + add() 기본값. 저장/재로드는 노드 통째라 자동 왕복.
- **schemas**: `AgentConfig.nodes`는 free-form dict라 통과(검증자는 prompt만 강제 — context는 정규화가 방어).

## 검증 (사다리)
- **단위** `verify_260_context_mode.py`: (1) normalize가 context 보존·잡값→carry, (2) clean 첫 진입이
  앞 결과만 입력으로 받고 이전 대화 제거(가짜 모델로 받은 messages 길이/내용 단언), (3) carry는 259 동작
  유지(무회귀), (4) clean+도구 재진입이 격리 buffer 유지.
- **통합**(브라우저 왕복, shot 확장): 2노드(carry→clean) 저작→생성→GET로 `nodes[].context` 보존.
- **무회귀**: verify_259 15/15 + tsc 0.

## 경계 (기록)
- clean의 "앞 결과" = 직전 노드의 최종 AI 응답(도구 루프 종료 후, 라우팅이 보장). 첫 노드 clean = 사용자
  입력만 있어 carry와 동일 효과(무해).
- 형식 **강제**(JSON 파싱·필드 검증)는 이 스펙 밖 — 프롬프트 유도만. 필요 시 후속(파서·에러 계약 별도).

## 결과 (구현·검증, 2026-07-09)

**구현**: pipeline.py — `normalize_nodes`에 `context`(carry/clean, 잡값→carry) + `_make_step`에 clean
격리 로직(첫 진입=마지막이 ToolMessage 아님 → `RemoveMessage`로 이전 대화 전부 제거 + 앞 결과를
`HumanMessage`로 새 입력, 도구 루프 재진입은 격리 buffer 위 carry 경로) + `_text_of` 헬퍼. 프론트 —
`PipelineNode.context` + NodeListEditor Segmented 토글(대화 이어가기/깨끗이 받기, 기본 carry, 설명 문구).
`_resolve_node_models`는 `{**n}`이라 자동 보존, 저장/재로드도 노드 통째라 자동 왕복.

**검증**:
- **단위** `verify_260_context_mode.py` 10/10: U1 normalize(context 보존·잡값→carry), U2 carry 기준
  (뒤 노드가 사용자입력+앞결과 모두 봄·누적 3), U3 clean 격리(앞 결과만·사용자입력 안 봄·이전 대화 제거
  리셋), **U4 clean+도구 재진입**(노드 2회 호출·첫 진입 격리·재진입 재-오염 0·도구 결과 격리 buffer에 보임).
  가짜 모델 몽키패치로 각 노드가 *실제 받은 메시지*를 기록해 동작 단언(구조 아님).
- **무회귀**: verify_259 15/15 + tsc 0.
- **통합**(브라우저 왕복, shot-pipeline-259.mjs 확장): 노드2를 "깨끗이 받기"로 전환→생성→GET로
  `nodes[0].context=carry`·`nodes[1].context=clean` 보존 실측(13체크 ALL GREEN).

**경계**: 형식 강제(JSON 파싱·검증)는 이 스펙 밖(프롬프트 유도만) — 후속 여지. 템플릿 표현식 미도입
(토글이 실수요 덮음).
