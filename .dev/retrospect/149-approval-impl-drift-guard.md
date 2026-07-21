# 149 — 승인 재개 impl-drift 명시 가드 (스펙 171)

개발자 "승인 로직 점검" 지시 → deep-reasoner 적대 검토 → 유일 실질 지적(Low) 처치.

## 발단
승인 로직 전반은 견고(인가 3-way·원자 TOCTOU·열거 오라클 차단·permission 서버 고정 — 다 방어됨).
단 하나: config-drift 가드 주석 "현 출하엔 HIL 커스텀 구현이 없어 미발생"이 **stale**. 이후 HIL impl
셋(DefaultUiAgent·orchestrate·orchestrate_ranked) 출하로 조건이 뒤집혀, impl-A→impl-B(둘 다 HIL)
교체 재개가 **도달 가능**해짐. 심각도 Low(admin 방아쇠·안전방향)지만 현 코드는 위상 불일치가 "예외로
곱게 흡수될 것"이라 *가정* — 정적 미확정 = **미정의 동작 의존**. 개발자 결정=명시 가드로 닫기.

## 한 것
`Approval.impl` 스냅샷 컬럼 + 생성 시 `ctx.get("impl") or ""` 스탬프 + 재개 시 `_impl_drifted`(순수
함수)로 대조해 다르면 graceful 거부(부수효과·build 이전). 마이그레이션·stale 주석 정정. 단위 10/10·
재개 멱등 회귀(116) 통과·deep-reasoner 재검토 "새 구멍 없음".

## 배운 것
- **조건부 안전 주장("현재는 미발생")은 시한폭탄**. codex F2가 "출하 impl 없어 미발생"이라 단언했는데,
  그 전제(출하 impl 목록)가 나중에 바뀌자 단언이 거짓이 되고 갭이 열렸다. **코드가 스스로 "안전하다"고
  단언한 근거가 외부 조건이면, 그 조건이 바뀔 때 깨지게(테스트/가드로) 하거나 아예 조건에 기대지 말 것.**
  주석의 "미발생"은 검증되지 않으면 stale된다 — 적대 리뷰가 이 stale 단언을 잡았다.
- **미정의 동작 의존을 명시 가드로 대체**. "예외로 흡수될 것"이란 가정 대신, 조건을 직접 검사해 거부 —
  LangGraph 내부 거동(예외/부분실행/fresh-run, 정적 미확정)에 안전을 걸지 않는다. 검증사다리에서 "실
  인프라 통합"이 답 못 준 자리를 *설계로* 우회.
- **같은 reviewer로 수정 재검토(SendMessage 컨텍스트 재사용)**가 효율적·고품질. 흐름 전체를 이미 쥔
  에이전트에 "이 수정이 새 구멍 여나"를 물어, fresh 에이전트가 흐름 재파악하는 비용 없이 5축(이중실행·
  배치·정규화·하위호환·타 불변식) 재검증. [[verification-ladder-three-rungs]]의 적대 rung 재적용.
- **잔여를 정직하게 *축소*하되 숨기지 않기**. 신규 행은 닫혔으나 pre-migration pending 행엔 남음(NULL-snap
  스킵) → 주석에 명시. 완전 제거(런타임 키 전체 스냅샷)는 OUT으로 미루되, 남은 창(유한·admin·일시적)을
  정직하게 문서화 = [[complement-attack-can-be-honest-boundary]]의 결.
- **스냅샷 필드가 다른 불변식 무접촉을 3중 확인**: 비노출(ApprovalOut 미포함=089-F1 정합, 열거 오라클
  신설 0)·비오버라이드(chat.py:146 화이트리스트 제외=세션 위조 불가)·비주입(ResolveIn=decision만). 새
  필드는 새 공격면이 될 수 있으니 노출/오버라이드/주입 3경로를 항상 점검.

## 검증
verify_171(단위 10/10 경계)·verify_116(재개 멱등 회귀)·API 리로드 200·마이그레이션 적용(alembic_version
e5f6a7b8c9d1, impl 컬럼 존재)·deep-reasoner 적대 재검토(새 구멍 없음·틈 닫힘).

## OUT
- 완전한 런타임 키 스냅샷(model/tools/persona까지) — impl 위상만 이번 범위. pre-migration pending 행의
  잔여(HIL→other-HIL, 유한·일시적). 다중 pending(순차 서브스텝 두 번째 승인 누락)=문서화된 §7 빚(083).

[approval-hil,impl-drift-guard,conditional-safety-claim-is-timebomb,replace-undefined-behavior-with-explicit-guard,reuse-reviewer-context,honest-residual-shrink,new-field-three-vectors]
