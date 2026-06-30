# 079 — deprecated API 마이그레이션은 대체 API를 추측 말고 실측·공식문서로 잡고, 가장 강한 기존 회귀로 계약 보존을 증명하라

## 상황
`create_react_agent`가 deprecated(`main.py:60`). 흔한 실수: deprecation 메시지의 새 이름만 보고
시그니처를 *추측*해 갈아끼우고 happy-path만 확인. 호출계약이 4종(invoke / astream messages /
astream 멀티모드+`__interrupt__` / `ainvoke(Command(resume))`)이라 단순 rename이 조용히 한 계약을 깰 수 있다.

## 배운 것 (일반화)
- **대체 API는 3겹으로 확정**(추측 금지): (1) **설치 패키지의 deprecation 메시지를 실측**
  (`inspect.getsource`로 `@deprecated` 본문 — "moved to X, use Y" 정확 문구), (2) **공식 문서로
  시그니처·breaking 확인**(파라미터 개명·제거), (3) 메타 패키지 설치 여부 확인(`langchain` 미설치였음 →
  의존성 추가 필요). 여기선 `prompt`→**`system_prompt`** 개명, 유일 breaking은 *콜러블 prompt 제거*
  (정적 문자열은 1:1 대응 → 우리 영향 0)임을 문서로 못박았다.
- **계약 보존은 "가장 강한 기존 회귀"로 증명**한다. 새 단위테스트를 짜기 전에, 이미 *실 인프라 통합*으로
  여러 계약을 동시에 태우는 회귀가 있으면 그게 1순위 증거다(verify_041: 실 MCP 도구 위 interrupt/resume/
  checkpointer 배선 G1-G7). **신규 스모크는 그 통합이 *안 덮는* 계약만 보완**한다(invoke·astream messages).
  새 테스트로 전부 재작성하지 말 것 — 기존 통합이 더 진짜다.
- **마이그레이션은 호출부 1곳에서 끝나지 않는다**: 같은 deprecated 심볼을 쓰는 *테스트 헬퍼·주석*까지
  쓸어야 deprecation 0이 된다(verify_041이 자체 헬퍼에서 옛 API를 2회 호출해 경고를 계속 냈다). grep으로
  "실제 호출 vs 주석"을 분리해 호출은 전환, 주석은 새 이름으로 정정.
- **deprecation 0을 단언으로 고정**: 스모크에서 `warnings.catch_warnings(record=True)`로 빌드 경로의
  `create_react_agent` DeprecationWarning 부재를 *테스트*했다(회귀가 새 deprecation을 다시 들이면 빨강).

## 어떻게 적용하나
deprecated API를 만나면: ① 설치본 deprecation 본문 실측 + 공식문서 시그니처/breaking 확인(추측 금지),
② 메타 패키지/의존성 추가 필요성 점검, ③ 호출계약을 *열거*하고 가장 강한 기존 통합 회귀로 보존 증명 +
빈 계약만 스모크 보완, ④ grep으로 전 사용처(테스트 헬퍼·주석 포함) 쓸기, ⑤ no-deprecation을 단언으로 박기.

## 근거
- 스펙 076. langgraph 1.2.5 `create_react_agent` `@deprecated`("use `from langchain.agents import
  create_agent`"), `langchain` 미설치→1.3.11 추가. `create_agent(model=, tools=, system_prompt=, checkpointer=)`.
  verify_041 G1-G7 PASS(deprecation 0), verify_076 C1 invoke·C2 astream messages·C3 no-deprecation PASS.
- 관련: [[probe-deeper-before-concluding]](새 이름만 보고 단정 말고 본문·문서 실측),
  [[verification-ladder-three-rungs]](단위 스모크 + 실 인프라 통합이 잡는 결함이 다름 — 통합이 1순위 증거),
  [[core-is-model-config-and-memory]](런타임 빌더=토대 → 엄격 검증).
