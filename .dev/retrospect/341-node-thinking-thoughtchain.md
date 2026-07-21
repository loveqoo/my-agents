# 341 — 노드형 사고 다단계 분리(스펙 413)

## 발단
개발자 "노드형은 노드마다 사고가 나올 수 있는데 렌더링 정책이 어떻게?" → 현재 SSE reasoning 프레임에
노드 태그가 없고 FE가 단일 필드에 통째 이어붙여 노드 A+B 사고가 한 패널에 뭉개짐(스펙 410 OUT).

## 무엇을 했나
- 백엔드: chat.py 스트림 루프가 `_meta.langgraph_node`를 reasoning 프레임에 `node`로 실음(축 분리
  불변식 유지 — reasoning은 여전히 본문·영속 미포함).
- FE: onReasoning(text, node)이 노드별 스텝(reasoningSteps)으로 누적(순차 실행이라 노드별로 몰려 옴).
  노드 2+면 `@ant-design/x ThoughtChain`(노드별 title·사고 접이·blink), 1이면 단일 `Think`(직접형 무회귀).

## 배운 것 (복리 후크)

- **유형별 다른 렌더는 "판정을 데이터에서"** — 직접형/노드형을 에이전트 타입 플래그로 분기하지 않고,
  **reasoning이 몇 개 노드에 걸쳤나**(reasoningSteps 길이)로 판정. 직접형은 자연히 1노드→1스텝→단일
  Think, 노드형은 2+→ThoughtChain. 타입 검사 없이 데이터가 렌더를 결정([[agent-type-capability-inspector-matrix]]의
  "유형마다 다른 메커니즘"을 판정 데이터로 통일 — 새 유형도 프레임만 맞으면 자동).

- **실측으로 전제 확정 후 설계** — LangGraph `_meta.langgraph_node`에 노드명이 실리는지 먼저 probe로
  확인(있었음)하고 설계. 없었으면 다른 축(observed 레코드)을 썼어야 [[verify-premise-before-designing]].

- **확률적·느린 모델은 결정적 단위로 우회** — 라이브 e2e(2노드 둘 다 사고)가 실모델 확률성·속도로
  timeout·미사고로 불안정(410과 같은 장벽). **fake reasoning 모델로 2노드 langgraph**를 돌려 노드
  태깅→노드별 스텝→ThoughtChain 판정을 결정적으로 증명. 라이브가 불안정한 로직은 결정적 재현으로
  담보(모델 stochasticity를 검증에서 제거) [[research-prior-art-before-expensive-probing]]의 "프로브
  변수 하나만"의 사촌 — 검증에서 비결정 요소(모델)를 fake로 고정.

## 검증
verify_413 5/5(결정적, 서버 불필요): U1 노드 태깅·U2 축 분리(본문 미포함)·U3a 2노드→ThoughtChain·
U3b 노드 순서/이름 보존·U3c 단일 노드→단일 Think(직접형 무회귀). tsc 0·FE 빌드. 라이브 e2e는 실모델
장벽으로 불안정 — 결정적 단위가 담보.
