# 171 — 승인 재개 impl-drift 명시적 가드

## 배경
승인 로직 적대 검토(deep-reasoner) 결과: 인가 우회·이중 실행·거부-실행 결함 **없음**(견고). 단 하나
실질 지적 — `chat.py`의 config-drift 가드 주석 "현 출하엔 HIL 커스텀 구현이 없어 미발생"이 **stale**.
지금 HIL 지원 impl이 셋 출하됨(DefaultUiAgent·orchestrate·orchestrate_ranked, 전부 `supports_hil=True`).
따라서 **impl-A→impl-B(둘 다 HIL) 교체**가 실제 도달 가능:

> 에이전트가 위험 도구로 Approval(pending, checkpoint=react 위상) 생성 → 결재 전 admin이 `config.impl`을
> orchestrate로 교체 → resolve 시 `resume_approval`이 supports_hil 가드(둘 다 True)를 통과해 **react가
> 만든 checkpoint에 orchestrate 그래프를 resume** → 위상 불일치 = LangGraph 미정의 동작.

심각도 Low(방아쇠가 admin에 갇힘=권한상승 아님·최악이 approved-but-not-executed=안전방향·게이트가
부수효과 전이라 무단실행 불가). 그러나 **현 코드는 이 불일치가 예외로 곱게 흡수될 것이라 *가정***하고,
그 거동이 정적으로 미확정 — 미정의 동작 의존이 냄새. 명시적 가드로 닫는다(구남님 결정).

## 딜리버러블
1. **Approval.impl 스냅샷 컬럼**(String(120), nullable). 생성 시점 impl 키를 박는다(위상 정체).
2. **생성**(`_create_approval`): `impl = ctx.get("impl") or ""`(기본=DefaultUiAgent는 "", 커스텀은 키).
3. **재개**(`resume_approval`): 스냅샷 `!= 현재 ctx.get("impl") or ""`이면 **graceful 거부**(HIL→non-HIL
   가드와 동일 패턴, 로그+return). 미정의 동작에 resume하지 않는다. `impl is None`(마이그레이션 이전
   행)은 대조 스킵(하위호환 — 옛 행은 스냅샷 부재).
4. **stale 주석 정정**: 다중 HIL impl 출하 사실 + 이제 명시 가드로 닫음 반영.
5. **마이그레이션**: approvals에 impl 컬럼 추가(down_revision d4e5f6a7b8c0).

## 판정 규칙
`snap = approval.impl`(None=이전행 스킵·""=기본·"key"=커스텀). `cur = ctx.get("impl") or ""`.
`if snap is not None and snap != cur: graceful 거부`. 안전방향(approved-but-not-executed) 유지.

## 검증
- 단위: 가드 predicate 경계(snap None→통과·""==""→통과·"orch"!=""→거부).
- 통합: 기본 impl로 Approval 생성 → 에이전트 config.impl을 orchestrate로 교체 → resolve → (a) 크래시
  없음(graceful), (b) 어떤 부수효과도 미실행, (c) approval은 결재됨. 자가검증 지양 — 실 DB 통합.
- 적대 재검토(deep-reasoner/codex)로 "명시 가드가 이중실행·무단실행을 열지 않는지" 확인.

## OUT
- 완전한 런타임 키 스냅샷(model·tools·persona까지 박아 재개) — impl 위상만 이번 범위(나머지는 config
  변경돼도 같은 impl이면 위상 동일, 게이트 유지). 다중 pending(순차 서브스텝 두 번째 승인 누락)은
  문서화된 §7 빚(retrospect 083)으로 별개.
