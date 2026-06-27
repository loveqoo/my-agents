# 037 — 파괴적 노브엔 바닥을 깔아라 (경계값이 곧 delete-all)

> 출처: 스펙 038 배치 세션정리 적대 리뷰. 관련: [[036-suspect-your-measurement-before-the-dependency]],
> 035-guard-the-source-not-the-copy, 회고 [[028-batch-foundation]].

## 증상

세션 보존정리: `cutoff = now() - timedelta(days=retention_days)`, `delete where last_activity < cutoff`.
`retention_days`는 단일 admin 필드(`int|None`, NULL=비활성). 적대 리뷰가 잡은 것:
**`retention_days=0`이면 cutoff=now() → 거의 모든 세션이 `last_activity < now()`라 전부 삭제 대상.**
음수면 미래시각이라 0건이지만, **0**은 "비활성"처럼 보이는데 실제로는 **delete-all**이다.

## 교훈

파괴적 작업의 입력 노브는 "유효 범위"만 검증하지 말고 **경계값이 어떤 사이드이펙트로 번지는지**를
물어라. `0`/빈문자열/`*`/빈 리스트처럼 "없음처럼 보이는 값"이 종종 **최대 파괴**로 매핑된다
(`IN ([])`는 SQLAlchemy가 막아주지만, `cutoff=now()`는 아무도 안 막아준다).

## 적용

- **API 경계에서 거부**: `session_retention_days: int|None = Field(default=None, ge=1)` — 1 미만 422.
  NULL은 명시적 비활성으로 허용, 0/음수는 입력 자체를 차단.
- **삭제 지점에서 또 한 번(방어층)**: `if days is None or days < 1: return disabled`. API 검증을
  우회한 경로(스케줄러·직접 호출·테스트)에서도 절대 전체 삭제로 번지지 않게. 035 "복사본이 아니라
  소스를 지켜라"의 변주 — *진실 게이트는 파괴 직전*에도 둔다.
- **테스트로 박제**: `retention=0 → status=disabled + 행 불변` 단언(verify_038 [4b]). 경계값 회귀 방지.
- **기본값은 비활성**: NULL → no-op. 운영자가 명시적으로 양수를 넣어야 삭제 시작(보수적 기본).

## 일반화

"되돌릴 수 없는 작업"의 모든 스칼라 입력에 대해 자문: *이 값이 0/빈/최대일 때 무엇이 지워지나?*
하나라도 "전부"면 바닥(`ge=1`)·천장·기본 비활성 중 필요한 가드를 입력 경계 **와** 실행 직전 양쪽에 깐다.
