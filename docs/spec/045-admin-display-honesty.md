# 045 — 어드민 표시 정직화: 승인 배지·목록 + A2A liveness

> 마스터 044 배치 1. UI 테스트 #12(승인 배지 2 vs 목록 8)·#2(A2A 등록 시 실존 테스트).
> 테마: **어드민이 보여주는 수·상태가 실제와 일치**하게. 관련: 스펙 041(HIL 승인 — 실 interrupt),
> 스펙 026/042(A2A 카드·실호출·SSRF), learning 028(서버측 fetch=보안표면),
> memory probe-deeper-before-concluding(추측 #2는 조사로 반증됨 — 카드는 이미 검증).

## 배경·문제

UI 테스트에서 두 "정직성" 결함:

- **#12 승인 배지 = mock 하드코딩.** 사이드바 배지는 `mockData.ts:345`의 `PENDING_APPROVALS`
  (= `ADMIN_APPROVALS.length`, 고정 2)를 쓴다(`AdminShell.tsx:25,104`). 반면 목록 화면
  `ApprovalsView`는 실제 `GET /approvals`를 부르는데, 이 엔드포인트는 **전 상태**(pending/approved/
  rejected)를 pending-우선으로 반환한다(`approvals.py:31`). 그래서 배지(2)와 목록(8)이 어긋난다.
  배지는 가짜 상수, 목록은 상태 필터 부재.
- **#2 A2A 등록 status = 무조건 online.** `register_external_agent`(`agents.py:341`)는 카드를
  fetch·검증(SSRF 가드 포함 — 이미 "실존 검증"은 함)하지만, **서비스 엔드포인트 liveness는 안 보고**
  `status="online"`을 무조건 박는다(`agents.py:375`). 카드가 published ≠ 실행 엔드포인트가 살아있음.
  사용자가 "테스트 없이 추가하는 것 같다"고 본 부분의 실체.

## 비범위 / 유예

- **가짜 시드 승인 행 제거**(seed.py:120-125의 데모 승인 — 뒤에 실 checkpoint 없음)는 **데이터
  정리라 050(dry-run)**으로. 본 스펙은 **코드 정직화**만. 045 후 배지=목록=실 pending(가짜 포함),
  050이 가짜를 비우면 자연히 줄어든다.
- A2A liveness는 **HTTP 도달성 probe**까지(짧은 타임아웃, 응답코드 무관 도달=live). 실 JSON-RPC
  핸드셰이크 ping은 부수효과·비표준이라 범위 밖. 도달 실패해도 **등록은 허용**(일시 다운 가능),
  status만 정직하게.

## 목표(완료 조건, 측정 가능)

1. **배지 = 실 pending 수.** mock `PENDING_APPROVALS` 임포트 제거. 사이드바 배지는
   `GET /approvals?status=pending` 길이(실 DB pending 행수)와 일치. resolve 후·뷰 진입 시 갱신.
2. **목록 = pending만.** `ApprovalsView`는 pending만 표시 — resolved 항목이 재로드 시 재등장하지
   않음. 빈 상태 문구("대기 중인 승인이 없습니다")가 의미와 일치.
3. **A2A status 정직.** 외부 등록 시 서비스 endpoint 도달성 probe → 도달이면 `online`, 아니면
   `offline`. 무조건 `online` 제거. 등록 자체는 막지 않음.
4. **검증 통과**: 백엔드 단위(probe·필터)·admin `tsc` 빌드·적대 서브에이전트 리뷰·브라우저 확인.

## 설계

### A. 승인 배지·목록 (#12)

- **백엔드** `approvals.py list_approvals`: 선택적 `status: str | None` 쿼리 파라미터 추가.
  주면 `WHERE status=:status`로 필터(여전히 pending-우선·requested_at desc 정렬 유지). 기본(None)은
  기존 동작(전량) 보존 — 다른 소비처 회귀 방지.
- **프론트** `api.ts listApprovals(status?)`: `?status=` 부가. `ApprovalsView`는 `'pending'`으로 호출.
- **프론트** `AdminShell`: `PENDING_APPROVALS` mock 제거 → `pendingCount` 상태. 마운트 시
  `listApprovals('pending')`로 카운트 fetch. (a) `view==='approvals'` 진입 시 refetch, (b) ApprovalsView
  에 `onResolved` 콜백 전달해 resolve 후 refetch. 배지는 `pendingCount` 사용.

### B. A2A liveness probe (#2)

- **백엔드** `agent_card.py`: `async def probe_endpoint(url: str) -> bool` 추가 — `guard_url`(SSRF)
  후 짧은 타임아웃(예 5s) HTTP GET/OPTIONS. 연결 성공(어떤 status여도)=live, 연결오류/타임아웃=dead.
  비밀값·예외 누출 없이 bool만.
- **백엔드** `register_external_agent`: 카드 fetch 후 `card.get("url")` probe → `status = "online" if
  live else "offline"`. 무조건 online 제거. probe 실패는 등록을 막지 않음(상태만 반영).

## 검증(자가 + 타자)

1. **백엔드 단위**: (a) `list_approvals(status='pending')`가 pending만 반환, 기본은 전량(회귀 없음).
   (b) `probe_endpoint`가 도달 URL=True, 미도달=False; SSRF 차단 URL은 False(예외 누출 없이).
   (c) 등록 시 미도달 endpoint면 status=offline.
2. **프론트 빌드**: admin `tsc`/`vite build` 통과(타입·미사용 임포트 제거 확인).
3. **타자(서브에이전트 적대 리뷰)**: "배지/목록/카운트가 또 다른 데서 어긋날 여지? status 필터가
   다른 소비처를 깨나? probe가 등록을 잘못 막거나 비밀 누출? online/offline 외 상태머신 충돌?"
4. **브라우저**(Playwright+시스템 Chrome): 승인 페이지에서 배지 수 == 카드 수 시각 확인.

## 검증 결과

모두 통과(2026-06-28).

1. **백엔드 단위** — `tests/verify_045_probe.py` 7그룹 ALL PASS:
   - P1 적대입력(None/빈/비http/숫자) → False, P2 loopback(127.0.0.1) → False(SSRF, 예외 미누출),
     P3 allowlist+응답(405도) → True(도달=live), P4 ConnectError → False(미도달=dead),
     P5 `list_approvals(status=None)` 시그니처(전량 기본 보존), **P6 `follow_redirects=False`
     (리다이렉트 SSRF 차단), P7 비-httpx 예외(ValueError)도 흡수 → False**.
   - P6/P7은 아래 적대 리뷰 후 추가.
2. **프론트 빌드** — admin `npx tsc --noEmit` EXIT=0(타입·미사용 임포트 정리 포함).
3. **타자(적대 서브에이전트 리뷰)** — 판정 FIX-FIRST, 지적 전부 반영:
   - **[High] probe `follow_redirects=True` → 리다이렉트 SSRF 우회**: `guard_url`은 최초 URL만
     검사 → 302로 내부 IP 우회 가능. **`follow_redirects=False`로 차단**(3xx도 도달=live로 충분).
   - **[Med] 좁은 `except httpx.HTTPError`**: probe "절대 raise 안 함" 계약 위반 가능 →
     **`except Exception`으로 확장**(등록 차단 방지).
   - **[Med] 배지·목록 이중 fetch 분기**: AdminShell `[view]` refetch + ApprovalsView 마운트
     fetch가 경합 → 한쪽 실패 시 배지≠목록 재발. **AdminShell을 마운트 1회(`[]`)로 고정**,
     승인 뷰의 카운트는 `onPendingChange` 단일 소스로.
   - **[Low] `setQueue` 리듀서 내부 side-effect**: StrictMode 이중 호출 노출 →
     **함수형 updater 유지 + 콜백은 밖에서 1회**(연속 resolve stale 클로저 되살림도 방지).
   - **[Low] pending-first 정렬 누락 / 스펙 모순**: 필터 분기에도 `pending_first` 유지.
   - **[Low] 죽은 mock `ADMIN_APPROVALS`/`PENDING_APPROVALS`**: 제거(가짜 승인 잔재).
4. **브라우저**(Playwright+시스템 Chrome, `tests/browser/shot-approvals-045.mjs`):
   - pending 0건일 때 배지 미표시 + 목록 빈 상태 → `MATCH_OK (0)`(하드코딩 "2" 환상 소멸 입증).
   - DB에서 2건 임시 pending flip → **배지 "②" == 목록 카드 2장 `MATCH_OK (2)`**(배지가 실제
     pending을 추적함을 입증), 검증 후 원복(비파괴 flip-restore, pending 0 복원).

## §7 빚·한계

- 배지 실시간성: AdminShell은 **마운트 1회** fetch + 승인 뷰 내 `onPendingChange` 갱신까지(폴링·
  웹소켓 아님). 승인 뷰 밖에서 타 클라이언트가 새 승인을 만들면 다음 마운트까지 배지 미반영 —
  다중 어드민 실시간 동기화는 본 스펙 밖(후속 폴링/웹소켓 후보).
- **에러 경로 배지≠목록**: ApprovalsView 로드가 네트워크 실패하면 목록은 빈/에러, 배지는 마운트
  시 값 유지 → 일시적 불일치 가능(영구 mock 거짓과 달리 transient). 치명도 낮아 유예.
- liveness는 등록 시점 1회 스냅샷 — 이후 죽으면 stale. 주기적 헬스체크는 후속(배치 잡 후보).
- 가짜 시드 승인 제거는 050로 유예(위 비범위).
