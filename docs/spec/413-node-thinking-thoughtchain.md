# 413 — 노드형 사고 과정 다단계 분리(ThoughtChain)

> 상태: **완료** · 2026-07-20 · verify_413 5/5(결정적 — 노드 태깅·축 분리·2노드 ThoughtChain·직접형 무회귀) + tsc 0 + FE 빌드
> 발단: 구남님 "노드형인 경우 thinking이 여러 번 나올 수 있는데 렌더링 정책이 어떻게 되나?" →
> 확인 결과(회고 338·본 스펙 Context): 현재 SSE reasoning 프레임에 노드 태그가 없고 FE onReasoning이
> **단일 reasoning 필드에 통째 이어붙여**, 노드 A 사고 + 노드 B 사고가 **한 패널에 뭉개진다**(스펙 410
> OUT — "ThoughtChain 노드형/조율형 후속"). 노드별로 갈라야 한다.

## 실측(전제 확정)
- LangGraph `stream_mode="messages"`의 `_meta`에 **`langgraph_node`**(노드 이름)가 실려 온다(probe로
  검색노드·검증노드 확인). → 프레임마다 어느 노드의 사고/출력인지 태깅 가능.
- `@ant-design/x` `ThoughtChain`: items=[{key,title,content,status,collapsible,blink}] — 노드별 스텝
  (title=노드명, content=사고 접이, blink=스트리밍 중)에 딱 맞음.

## 설계 — 유형별 다른 렌더(직접형 무회귀)
- **직접형(단일 노드)**: 현재 `Think` 단일 패널 유지(무변경). reasoning 프레임이 한 노드라 그대로.
- **노드형(다중 노드)**: `ThoughtChain`으로 노드별 스텝 — 각 노드=title(노드명)+content(그 노드의 사고,
  접이·마크다운)+blink(그 노드 스트리밍 중)+status(진행/완료). 최종 답변은 기존 메인 말풍선(무변경).
- **판정**: reasoning이 **2개+ 노드**에 걸치면 ThoughtChain, 1개면 단일 Think(직접형·단일 노드 무회귀).

## 구현
- **P1 백엔드 — reasoning 프레임에 노드 태그**: chat.py 스트림 루프가 `_meta.get("langgraph_node")`를
  reasoning 프레임에 `node` 필드로 실는다(`{"reasoning":"...","node":"검색노드"}`). content 프레임도
  선택적으로 node 태그(향후 노드별 출력 표시 여지 — 이번엔 reasoning 우선). **축 분리 불변식 유지**:
  reasoning은 여전히 acc/영속 미포함, node는 표시 메타만(스펙 410 관문 정화 그대로).
- **P2 FE 모델 — 노드별 누적**: ChatMsg에 `reasoningSteps?: {node: string, text: string}[]`(순서 보존).
  `onReasoning(text, node)`가 그 노드 스텝에 누적(없으면 새 스텝 append). 단일 reasoning 필드는
  하위호환(node 없으면 기존 단일 누적). streamChat 클라가 프레임의 node를 onReasoning에 전달.
- **P3 FE 렌더 — DebugChat**: `reasoningSteps` 노드 수 ≥2면 `ThoughtChain`(노드별 아이템: title=노드명,
  content=`MessageContent`(사고), collapsible, blink=현재 스트리밍 노드), 1이면 기존 단일 `Think`.
  노드명 표시: langgraph_node id 그대로(있으면 에이전트 nodes의 표시명 매핑 — 여의치 않으면 id).
- **P4 검증**: 단위(프레임에 node 실림·onReasoning 노드별 누적·2노드→ThoughtChain 판정) + 브라우저
  e2e(노드형 thinking 에이전트 → ThoughtChain 노드별 스텝, 실측 — 모델 사고 확률적이라 재시도/강제
  프롬프트). 직접형 무회귀(단일 Think 유지) 확인.

## OUT
- 노드별 **출력(content)** 을 ThoughtChain 스텝에 넣는 풀 파이프라인 시각화(이번은 사고 축만·최종
  답변은 메인 말풍선) — 후속. 조율형(orchestrate) 위임 사고 표시도 후속(노드형 먼저).
- ThoughtChain status(성공/실패) 정밀 매핑(노드 오류 표시) — 후속.

## 완료 기준
- [x] reasoning SSE 프레임에 node(langgraph_node) 실림 — verify_413 U1(결정적: 2노드 그래프).
- [x] onReasoning 노드별 누적(reasoningSteps)·streamChat이 node 전달 — verify_413 U3 + tsc.
- [x] 노드형 2노드 → 노드별 ThoughtChain 스텝(사고 분리) — verify_413 U3a/U3b.
- [x] 직접형 무회귀: 단일 노드 → 단일 Think — verify_413 U3c.
- [x] 축 분리 불변식(reasoning 본문·영속 미포함) — verify_413 U2 + FE 빌드.
      **라이브 e2e 주의**: 실모델(MLX)의 확률적·느린 thinking 때문에 브라우저 e2e(2노드 둘 다 사고)가
      timeout·미사고로 불안정 → 로직은 결정적 단위(fake reasoning 모델)로 담보(410과 같은 모델 장벽).
