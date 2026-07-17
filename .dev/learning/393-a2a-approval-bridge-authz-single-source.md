# 393 — A2A 승인 브리지(388 P2): "같은 재개 함수 공유"는 "같은 인가"가 아니다

## 맥락

승인 브리지 P2: 서빙 interrupt→Approval 변환, A2A metadata {approvalId, decision}로 재개.
원자 UPDATE+resume_approval을 REST와 공유해 "같은 시맨틱"이라 주장했는데, codex가 P1을 적중:
**재개 함수는 공유했지만 결재 인가(_may_resolve)는 안 거쳤다** — 비-admin 쿠키 유저가 A2A로
자기 승인을 셀프 approve해 위험 도구를 실행할 수 있었다(REST에선 admin/self-approve만 허용).
resolve_and_resume에 principal을 넣어 _may_resolve 공유로 봉합(-32003). verify_388 22/22.

## 교훈

- **"같은 백엔드 함수를 공유한다" ≠ "같은 게이트를 지난다."** REST 라우트의 보안은 함수 하나가
  아니라 [인증 → 인가(_may_resolve) → 원자 전이 → 실행] 사슬 전체다. 새 입구(A2A)가 사슬의
  뒤쪽 함수만 재사용하면 앞쪽 게이트가 통째로 빠진다 — [[policy-at-the-chokepoint]]의 실패 모드:
  관문보다 아래 레이어에서 재사용하면 관문이 안 씌워진다. 새 입구를 낼 땐 기존 입구의 **게이트
  목록을 먼저 적고**(인증·인가·전이·감사) 하나씩 대응을 확인하라.
- **적대 리뷰 프롬프트에 "기존 입구의 게이트 대응표"를 요구하는 게 효율적** — 내 보장 목록 5번
  ("REST 무변경·같은 재개 공유")이 정확히 그 빈칸을 가렸고, codex는 REST 경로를 따라 읽으며
  _may_resolve 부재를 찾아냈다. 보장을 "무엇을 공유"가 아니라 "어떤 게이트를 지나는가"로 쓰라.
- **인프로세스 검증은 lifespan 초기화 목록이 필요하다** — checkpointer(HIL)·authz(casbin)가
  없어 테스트가 다르게 돌았다(체크포인터 없음=승인 자체가 안 생겨 P2가 조용히 통과 못 함/
  authz 미초기화=RuntimeError). ASGI 인프로세스 검증기는 앱 lifespan이 하는 init 목록
  (init_checkpointer·init_authz)을 명시 호출 — 셋업 표를 테스트 헤더에 남겨라.
- **복잡도 게이트가 즉시 잡았다(386 재현)** — P2 추가로 E/D 두 함수. 응집 조각(스트림 제너레이터·
  도구 조립·응답 조립·메타 파싱)을 모듈 레벨 헬퍼로 — 내부 클로저는 부모 CC에 합산되므로
  "함수 안 async def"는 복잡도 도피가 안 된다.

[shared-function-is-not-shared-gate, list-gates-before-new-entrance,
inprocess-tests-need-lifespan-inits, inner-closure-counts-into-parent-cc]
