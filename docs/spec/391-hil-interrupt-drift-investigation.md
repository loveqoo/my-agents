# 391 — verify_101/102 "인터럽트 미발동" 조사: P0 아님 — 177 스키마 화석

> 상태: 조사 스펙(계획 승인 2026-07-18). 발단: 스펙 390 재판정에서 "delete→interrupt 미발동이
> virgin 서버에서도 재현 = 실드리프트" 상향 — 승인 게이트 우회(P0) 가능성 배제가 목적.
> 참고 자산: learning 110(각 고리≠체인·principal 타입)·144(HIL 결정 발동 조건)·103/105(두 게이트
> 분리·approval_for non-None)·스펙 041/101/177 P2·회고 082(stale split-brain 배제)

## 판정: **P0 아님 — 승인 게이트 정상, 테스트 단언의 스키마 화석**

전체 캡처 정밀 판독으로 확정:
- H6의 **첫 단언만** 실패하고 직후 단언 전부 통과 — pause 시 전송 0 ✓ → approve 재개 정확히
  1회 전송 ✓ → reject 재개 전송 0 ✓ → **실 HTTP 채팅 왕복(H7) 전부 정상**(승인 프레임 발급·
  approve 재개·reject). 즉 interrupt는 뜨고, 승인-이전-무실행 불변식(041 §3.3)도 성립.
- 자립 프로브로 interrupt payload 실물 확보:
  `{permission: "mcp.local-tools.delete_record", approver: "admin", action: "local-tools.delete_record", …}`
  — **스펙 177 P2가 permission을 구조화 형식으로 재편하고 인가 판정을 approver 필드로 이동**
  (_may_resolve와 동일 진실원). 실패한 단언 `permission == "data.delete"`는 그 이전 스키마의 화석.
- 390의 "virgin에서도 재현 = 실드리프트" 상향은 반은 맞았다: 재현되는 드리프트는 맞으나
  **제품이 아니라 테스트 쪽**이었다(단위 U4의 approval_for="data.delete" 계약은 별개 층으로 여전
  유효 — 통합 payload만 177 형식).

## 조치

- 101 H6·102 H8/H10 단언을 현 스키마로 현행화 — 판정 필드(approver)+action 기준(177 정신:
  permission 문자열 매칭 지양). → **101·102 virgin 서버 그린, 격리 해제(-2)**.

## 완료 조건(측정) — 결과

- 101·102 virgin 서버 exit 0 ✓ · 격리 −2 ✓ · metrics-fast·make test 그린(실행 중 확인).
- P0 배제 확정: 승인-이전 전송 0·재개 1회·거부 0·실 HTTP 왕복 그린(코드 무변경 — 제품 결함 아님).
