# 294 — 파이프라인 도구 결과 신뢰 경계 통일 (인젝션 펜스, 스펙 319)

스펙 318 적대 리뷰 P2 후속. 조율형(orchestrate)이 가진 데이터 채널 격리(nonce 펜스 + 방어 지침)를
파이프라인(노드형) 도구 결과(MCP·RAG·에이전트호출)에 통일. 문서 인젝션·악의적 도구 출력·위임 결과의
"이전 지시 무시" 텍스트가 상위 노드를 조종하지 못하게 하한을 세운다.

## 배운 것

- **실행기계의 구조 차이가 이식 방식을 가른다.** 같은 격리 목표라도 조율형은 위임을 **명시적 fold
  서브스텝**으로 감싸 데이터 채널(Human)에 담고, 파이프라인은 **표준 ReAct `ToolNode`**가 결과를 raw
  ToolMessage로 넣어 루프 안에서 재진입한다. 그래서 이식은 "fold 재사용"이 아니라 **ToolNode 후처리
  래퍼**(`_fenced_tool_node`)로 각 ToolMessage.content를 펜스. 배선이 다르면 같은 원자(fence_wrap)를
  공유해도 조립점이 달라진다 — deep-reasoner에게 옵션 비교를 맡겨 이 차이를 먼저 드러낸 게 주효.
- **도구 빌더에서 감싸는 "쉬운 옵션"의 폭발반경.** `_wrap_mcp_tool` 등 도구 빌더 반환값을 펜스로 감싸면
  단순해 보이나, `ctx.tools`를 **DefaultUiAgent·plan_execute도 소비**한다(runtime.py·examples). 이들은
  방어절 없는 sys라 펜스 마커를 설명 없는 노이즈로 받는다 → 품질저하 + 크로스패키지 암묵계약 누출.
  **국소성(pipeline.py 안에서만)이 안전.** learning 099 "확장점 위치가 보안 속성을 가른다"의 재현 —
  같은 기능도 *어디서* 감싸느냐가 폭발반경을 정한다. 폭발반경은 상상이 아니라 소비자 grep으로 측정.
- **방어 지침은 nonce 값을 몰라도 된다(결정성의 열쇠).** 조율형 attribution이 리터럴 `⟦BEGIN …⟧`
  (말줄임표)만 쓰고 실제 nonce 토큰을 문자열에 안 넣는다(존재 여부로만 분기). 그래서 파이프라인 sys도
  **정적 방어절**(nonce 미포함)이면 충분 → 매 `_step`이 sys를 새로 조립해도 랜덤 미개입=**결정적**
  (단위 검증 가능). nonce는 한 wrap 내부 BEGIN/END 짝맞춤에만 필요.
- **content 미파싱 판정이 펜스를 airtight하게 만든다.** 가장 위험했던 회귀 후보 `_count_tool_rounds`가
  ToolMessage를 **타입만 보고 content를 파싱 안 한다**(reentry·format=json도 동일). 펜스가 content를
  바꿔도 이들이 안전 — "타입만 보는 판정"이 우연히 안전 여백을 준다. 회귀 후보를 세워 각각 근거로 배제.
- **langgraph config 주입은 bare `RunnableConfig`.** ToolNode를 래핑하면 그래프 엔진이 노드에 주입하는
  config를 관통해야(InjectedToolArg·store). 근데 `RunnableConfig | None` 애노테이션은 langgraph 1.2.5
  문자열매칭 주입에 실패(UserWarning) — bare `RunnableConfig`여야 주입된다(learning 277 produce_node
  회귀와 동일 클래스). 경고가 회귀 가드 역할.
- **행위보존 리팩터는 기존 verify가 핀.** `fold_results`의 `⟦BEGIN⟧…⟦END⟧` 조립을 `fence_wrap` 재사용
  으로 바꿔도 verify_115가 nonce 펜스·위조 격리·결정성·레거시 raw를 바이트 단위로 확인 → 안전하게 추출.
  단일 출처(fence_wrap)로 조율형·파이프라인 드리프트 0.
- **적대 P3는 코드결함 아니라 스펙 정밀도.** codex가 "펜스가 trace.sentMessages로 노출"을 지적. 그러나
  sentMessages는 **"모델이 실제로 본 것"의 ground truth**라 펜스를 보여주는 게 정확하다(신뢰 경계 적용을
  인스펙터에서 확인 가능 — 정밀 디버그 통로 원칙). "인스펙터 raw"는 **도구 결과 기록(calls_sink)** 얘기
  였을 뿐 — 두 관측 채널(무엇을 받았나 vs 무엇을 봤나)의 목적이 다르다. 스펙 문구를 정밀화(정직화).
- **정직 경계**: LLM은 인젝션을 100% 못 막는다. 펜스·채널 격리는 **하한**(learning 052). 코드 노드는
  신뢰 저작 코드라 자기 트러스트 경계를 스스로 책임(펜스 밖, 의도된 경계).

## 검증

- 단위 verify_319(U1~U5): fence_wrap 정확·fold_results 행위보존·_fenced_tool_node 실 ToolNode 펜스
  (1노드 그래프)·_count_tool_rounds 불변식·방어절 상수. **그래프(G0~G3, 스텁 모델)**: 모델이 실제로
  받은 sys에 방어절·재진입 ToolMessage 펜스 격리·위조 ⟦END⟧ 펜스 안.
- 회귀: 115(fold 행위보존)·259·260·261·315·317·318 전부 green. mypy(108)·ruff 클린.
- 적대(codex 여집구): P1/P2 보안 우회 0. P3(sentMessages 노출)=ground truth라 정직화(코드 무변경).
  막힌 축: 펜스 탈출(nonce 사후생성)·입구 정합(_fenced_tool_node 단일)·행위보존·config 주입.

## 관련
[[293-node-agent-call]](P2 발원) · 확장점 위치=[[why-build-multi-agent-platform]] 근처 learning 099 ·
정직 경계=[[complement-attack-can-be-honest-boundary]] · 정밀 디버그=[[playground-is-precision-debug-channel]] ·
config 주입 회귀=[[reload-reruns-migrations-mid-edit]] 인접(langgraph 1.2.5 문자열매칭 learning 277)
