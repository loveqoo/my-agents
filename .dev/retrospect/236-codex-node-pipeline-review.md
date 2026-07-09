# 236 — codex 적대 리뷰: 노드형 파이프라인(259-261)의 세 번째 입구 (codex 후속)

## 맥락
사용자 요청 순서 #2 = 259+260+261 묶어 codex 적대 리뷰. 7개 각도(시크릿 누출·권한상승·clean
재-오염·JSON 관대추출 DoS·모델해석·eval·페이로드 DoS)로 read-only 검토. 4건 발견, 각 코드로 확증.

## 무엇을 배웠나

### 1. "주입 2지점"이라 스스로 적었는데 실은 3지점이었다 (learning 088 정통 사례)
retrospect 233에 "impl_config 주입 2지점(메인 ~904, 재개 ~1471)"이라 적었다. codex가 **세 번째
입구**(`stream_local_reply` chat.py:762 = A2A 서빙)를 짚었다 — 여기만 `impl_config`를 안 넘겨,
노드형/산출물형 에이전트를 A2A로 노출하면 기본 단일 노드("사용자 입력에 답하세요")로 **퇴화**한다.
`_load_context`가 `nodes_resolved`를 이미 계산해 ctx에 있는데 이 build_ctx만 안 실었다. 즉 데이터는
있고 배선만 빠진 전형적 dead-contract(learning 088). **교훈: "모든 입구를 셌다"는 자가선언이 바로
맹점** — 내가 센 2지점이 닫힌 집합이 아니었다. codex(타자)가 3번째를 찾았다. 입구 열거는 grep으로
(AgentBuildContext 생성 지점 전수), 기억으로 하지 말 것.

### 2. "개수만 캡, 크기는 무제한"은 절반의 가드
스키마가 nodes≤50만 캡하고 각 노드는 `dict[str, Any]`라 prompt·fields가 무제한이었다(codex P2).
50개 캡이 "제한 있음"의 착시를 준다 — 실제 DoS 표면(멀티MB prompt × 50)은 열려 있었다. 캡은
*모든 축*(개수 + 각 필드 크기 + 리스트 길이)에 걸어야. learning 041(리밋은 원천 바이트) 결.

### 3. 임의 키 보존은 편의이자 비밀 에코 풋건
`dict[str, Any]`가 임의 키를 저장·에코해서, 직접 API 호출자가 `nodes[].model_cfg.api_key`를 심으면
`AgentOut.nodes`로 되돌아온다(codex P3). 플랫폼 비밀 누출은 아니지만(자기 비밀), 계약이 "무엇이든
저장·반사"라 위험. 처방: **키 화이트리스트**로 알려진 필드만 저장(model_cfg 등 드롭). 자유 형태
편의를 신뢰경계로 좁혔다(learning 075 결). H1~H5 단위로 못 박음.

### 4. codex가 "의도된 정직 폴백"과 "버그"를 갈라줬다
P3 #4(JSON 실패 시 원문 통과)를 codex가 "Contract Risk"로 올렸지만, 이건 235에서 *의도적으로* 택한
정직 폴백(거짓 JSON 조작 거부). codex 지적의 유효 부분은 "조용함" — 소비층이 format=json을 신뢰하다
실패. 그래서 **조작은 유지(원문 통과), 관측 로그만 추가**(운영 인지). 적대 리뷰가 옳다고 다 고치는 게
아니라, 판정을 재확인하고 *유효 부분만* 흡수(complement이 항상 코드결함은 아니다, learning 072 결).

### 5. codex가 확인해준 안전도 자산 — 기록
시크릿 미유출(model_cfg는 ctx에만·AgentOut.nodes는 저장 config만)·권한상승 불가(node 도구는
ctx.tools 멤버십 필터, 밖이면 무)·clean 격리 건전(재-오염 순서 못 찾음)·eval 없음(노드=데이터). "없다"도
근거와 함께 정직한 산출물(ui-audit 규율). 다음 리뷰가 같은 각도 재검토 안 하도록 남긴다.

## 조치 (커밋)
- chat.py:762 — A2A 서빙 build_ctx에 impl_config 주입(메인·재개와 동일, 3지점 정합).
- schemas.py `_check_nodes` — 키 화이트리스트 + 필드별 상한(prompt 20000·tools/fields 100·문자열 200).
- pipeline.py `_finalize` — JSON 강제 실패 시 log.warning(은폐 완화).
- verify_codex_259_261_hardening.py 12/12 + 259/260/261 무회귀 + 브라우저 왕복 그린.

## 잔여
- A2A 서빙 e2e(노출→JSON-RPC 호출로 노드 실행)는 코드-미러(검증된 메인 경로와 동일)로 확신, 실호출
  검증은 #1 execute e2e에서 A2A 각도로 확장 가능.
