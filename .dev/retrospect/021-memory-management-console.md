# 021 — 메모리 관리 콘솔 (스펙 030) 회고

날짜: 2026-06-26 · 브랜치 `feat/agent-service` (main 미머지)
스펙: [030](../../docs/spec/030-memory-management-console.md) · 선행: 018(유저 스코프), 020(다층), 029(에이전트 전용)

## 무엇을 했나

사용자 지적("에이전트 메모리, 유저 메모리를 검색·수정할 메뉴가 없다")에 답해 통합 "메모리" 메뉴를
넣었다. 탭 둘(에이전트/유저), 검색은 목록+텍스트 필터, 029 상세 패널은 유지. 백엔드는 유저 스코프
라우터(`/memory/user/{user_id}` list/update/delete)를 신설하고, chat.py의 mem_cfg 조립을
`_build_mem_cfg`로 추출해 `default_mem_cfg`(기본 chat+embedding)와 공유했다.

## 잘된 것

- **029 자산이 그대로 복리가 됐다.** `AgentMemoryPanel`을 새 화면에서 재사용했고, 유저
  패널은 그 동형(add만 뺀)으로 빠르게 나왔다. 소유권 가드도 029 `_assert_owns`를 그대로
  user_id 판으로 복제 — 패턴이 있으니 빈틈이 안 생겼다. [[027-frontend-filter-is-not-a-backend-guard]]에서
  배운 "프론트 필터는 가드가 아니다"가 이번 `_assert_user_owns`로 자동 반영됐다.
- **검증을 타자에게 맡겼다.** 라이브 라운드트립 + 소유권 가드 404 + 브라우저(Playwright) +
  서브에이전트 적대 리뷰. 자가검증 지양 원칙을 지켰고, 리뷰가 LOW 2건(mem_id 인코딩·empty-text
  가드)을 잡아줘 바로 보강했다. 둘 다 029에서 상속된 fail-safe 결함이라 "새 결함은 0"이었다.
- **단정 전에 한 겹 더.** 브라우저 콘솔 404를 보고 바로 "버그"로 적지 않고 API 로그를 확인 —
  내 의도적 소유권 가드 테스트(bob 경로)뿐이었고, 콘솔 404는 정적 자산(메모리 기능 무관)이었다.
  [[probe-deeper-before-concluding]] 적용.

## 거칠었던 것 / 교훈

- **antd Select·Tabs 하니스 함정.** 브라우저 검증 첫 판은 Select 옵션을 placeholder 텍스트
  클릭으로 고르려다 실패(옵션은 포털 `.ant-select-dropdown`에 렌더). showSearch에 타이핑→
  `.ant-select-item-option` 클릭으로 고쳐야 했다. 또 antd Tabs는 **비활성 탭도 마운트**(display:none)
  →필터 인풋이 둘이라 `.first()`가 숨은 쪽을 잡아 fill 타임아웃. `locator('visible=true')`로 해결.
  → 학습 [[032-antd-portal-and-mounted-tabs-break-naive-selectors]]로 적립.
- **공유 빌더 리팩터의 무회귀 입증은 git diff로.** chat.py를 손대며 029가 깨질까 걱정됐는데,
  리뷰 서브에이전트가 029 커밋(493721d)과 byte 비교해 "behavior-preserving" 확인 — 회귀 불안은
  추측이 아니라 과거 커밋 대조로 끝낸다.

## 다음에 적용할 것

- UI 검증 하니스를 만들 때 antd는 **포털 렌더 + 전체 마운트**를 기본 가정하라(학습 032).
- 새 mem0 변조 경로를 추가하면 **반드시** path 스코프 소유권 가드부터 — 공유 pgvector에선
  id-only op가 곧 교차-스코프 변조다(029/030 불변). 가드 없는 update/delete는 작성 금지.
