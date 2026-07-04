# 148 — 평가 도구 정직성 (평가 통과 ≠ 도구 호출) (스펙 170)

구남님 관찰: "평가는 통과하는데 실제 대화에선 도구가 잘 안 불린다." 근인을 코드에서 찾음.

## 근인
프레임워크엔 `trace_has`/`trace_lacks`(실제 호출 도구 채점)가 **이미 있었고 UI도 노출**했다. 문제는
**출제 습관** — 케이스 기본 assert가 `no_error`+`output_nonempty`뿐이고 아무도 도구 검사를 넣으라
찔러주지 않아, 모델이 도구를 안 부르고 자기 지식으로 그럴듯한 답만 내도 통과. **거짓 초록이 출제
시점에 태어난다.** 능력 부재가 아니라 *신호 부재*였다.

## 한 것 (admin EvalView.tsx만, 백엔드 무변경 — 성적표가 이미 케이스별 obs.trace_nodes 보유)
- ① 성적표 "도구 미사용" 배지 + 상단 집계("도구 미사용 N건"). `firedTool`=trace_nodes에 `rag:`/`mcp:`/
  `memory:` 접두 하나라도. 통과인데 흔적 0 → 표시. **기존 시험 결과에도 소급**.
- ② 출제 편집기 안내: agent 케이스에 trace_* 없으면 조용한 경고(막지 않음).

## 배운 것
- **능력이 있어도 "쓰이도록 찔러주지" 않으면 거짓 초록이 난다**. `trace_has`는 처음부터 있었지만
  기본값·유도가 없어 아무도 안 썼다. 크래프트 자산화의 핵심은 *기능 추가*가 아니라 **기본을 정직 쪽으로
  기울이는 것** — 재발을 막는 신호를 심는 것([[craft-first-then-compound-as-asset]]).
- **진단 정직성 패턴을 평가 표면에 확장**(158/162/164 계열): 실패/빈/미설정을 제 이름으로 부르듯,
  "통과지만 도구 미호출"도 제 이름으로. 성적표가 이미 obs.trace_nodes를 들고 있어 **소급 표시가 공짜**
  (백엔드 무변경). 관측 데이터는 이미 있는데 *결론을 안 내려주고* 있었을 뿐.
- **중립 표시 > 버그 단정**: 도구 미사용은 순수 대화 케이스에선 정상 → 주황 사실 태그로만, 안내는
  비차단. 과잉 강제(모든 케이스 trace 필수)는 과잉 억제와 같은 실수(감사 143 교훈의 평가판).
- **검증은 iff로 못박기**: 브라우저 실측 + "도구 흔적 0 ⇔ 배지" 일관성 assert. mock-llm이 도구를
  안 부르는 성질(trace=plan/execute 그래프 노드만)을 이용해 도구 미호출 통과를 결정적으로 재현.
- **테스트 함정 2건**: 평가 에이전트 select 라벨은 alias 아닌 **name**('plan-execute-demo'). 실패한
  e2e가 데이터셋을 남겨 모달 충돌 → **멱등 정리**(시작 시 잔여 행 삭제)+마스크 hidden 대기로 안정화.

## 부수 발견(백로그)
Icon name="info-circle"는 맵 키가 없어 fallback(appstore) 아이콘이 뜬다 — 맵 키는 `info`. AgentsView:1950도
동일 버그(무해하나 오아이콘). 170에선 `info`로 바로잡음.

## 검증
`shot-eval-tool-honesty-170.mjs` PASS: ② 안내 표시·① 배지+집계·1/1 통과·trace 도구흔적 0·iff 일관성.
스크린샷 육안(성적표 "도구 미사용 1건", 편집기 주황 안내).

## OUT
- 도구 호출 신뢰도 자체(모델 능력·프롬프트 유도)는 별개 축. 저장 차단(비차단 유지). 메모리 vs
  히스토리 체감(구남님 의문 ①)은 별도. info-circle 아이콘 잔존 버그(AgentsView).

[eval-tool-honesty,false-green-born-at-authoring,nudge-defaults-toward-honesty,retroactive-signal-from-existing-obs,neutral-not-bug-verdict,iff-verification]
