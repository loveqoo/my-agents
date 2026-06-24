# 012 — Playground userId UX + 피드백 9건 + #9 인스펙터 겹침 (AI 회고)

날짜: 2026-06-25
브랜치: `feat/agent-service` (main 머지·push 금지 — 사용자가 직접 브랜치 테스트)
스펙: [021-playground-userid-ux](../../docs/spec/021-playground-userid-ux.md)
연관 코드: `admin/src/playground/{Playground,DebugChat,Inspector}.tsx`, `admin/src/api.ts`, `packages/api/src/api/{chat,sessions,models}.py`, alembic `d2e3f4a5b6c7`

---

## 무엇을 했나

1. **스펙 021 본체** — userId를 세션에 영속(`sessions.user_id` 컬럼 + 마이그레이션), `GET /sessions/users`(distinct·최근순), 헤더 `Input`→`AutoComplete`(과거 userId 선택 + 자유 입력).
2. **진행 중 userId 잠금** — 대화가 시작되면(`messages ≥ 1`) userId 입력을 `disabled`, "새 대화" 버튼으로만 초기화·해제. mem0 스코프 혼선(run_id recall bleed) 원천 차단.
3. **사용자 브라우저 피드백 9건** 연속 처리:
   - #1 입력창 안 비워짐 → Sender controlled + submit 시 `setDraft('')`.
   - #2 트레이스 도착 시 인스펙터 자동 열림(불편) → `onTrace`의 `setInspectorOpen(true)` 제거.
   - #3 응답 시작 전 빈 말풍선 멈춤 → Bubble `loading`(점 애니메이션) on `!m.text`.
   - #4 잘못된 메모리 수정 방법 → 별도 스펙으로 보류(trace `id` 노출 필요).
   - #5 연결 모델 확인 → AgentCombo 부제에 모델 칩(primary 배경).
   - #6 파일첨부 아이콘 → 일단 그대로.
   - #7 응답 끝났는데 전송 버튼 빙글빙글 → `onTrace`에서 `setStreaming(false)`(트레이스=턴 완료 신호).
   - #8 userId 입력 폭 과다 → 150/110px로 축소.
   - #9 인스펙터 열면 아이콘 겹침 → **아래 별도 분석**.

## 무엇이 잘못됐고 무엇을 배웠나

### #9: 측정과 사용자 눈이 어긋났을 때
- 1244/900/600px에서 bounding-box 측정 = "겹침 없음". 그런데 사용자 스크린샷엔 명백히 겹침.
- **나는 같은 폭들을 반복 측정하며 헛돌았다.** 모바일 오버레이 z-index 스태킹까지 의심했지만 다 빗나감.
- 사용자가 **"어중간한 넓이일 때 발생, 다양한 폭으로 테스트하라"**고 짚어주자, 760~1220px 폭 스윕 한 번으로 즉시 재현(780~880px 헤더 오버플로).
- **교훈**: 측정값이 사용자 시각 보고와 어긋나면, *같은 점을 다시 재지 말고 파라미터(여기선 폭)를 스윕*하라. 그리고 "재현 조건이 뭐냐"를 **사용자에게 더 일찍 물었어야** 했다(메모리 [[probe-deeper-before-concluding]]와 같은 결).

### #9 근본 원인 — 뷰포트 브레이크포인트의 거짓말
- `Grid.useBreakpoint()`는 **뷰포트 전체 폭**만 본다. 사이드바(232) + 인스펙터(384)가 같은 행을 먹는데 그걸 빼지 않는다.
- 그래서 `compact = !screens.lg`(992)는 side-by-side가 시작되는 바로 그 폭에서 헤더를 풀 라벨로 키워 404px 컬럼에 넘치게 만들었다.
- 수정: (a) 오버레이 임계값 `md`→`lg`(좁으면 전체화면), (b) `compact = !screens.lg || inspectorOpen`(인스펙터 열리면 무조건 축소). → learning [[022-viewport-breakpoints-ignore-sibling-panels]].

### 검증 방식
- Playwright로 폭 스윕 + 스크린샷 자가 검증. 사용자에게 스크린샷을 떠넘기지 않고 내가 확인(사용자 선호). [[016-verify-ui-before-test-guide]]의 연장.
- 한계: 스윕 중 뷰포트 리사이즈 후 인스펙터가 빈 상태로 보이는 *리마운트 아티팩트*가 있었다 — 폭별로 대화를 새로 수립하면 콘텐츠 정상. 합성 리사이즈 결과를 그대로 믿지 말 것.

## 다음에 적용할 것
- 반응형은 **콘텐츠 영역 잔여 폭** 기준으로 판단(사이드바·패널을 뺀 값). 뷰포트 폭 그대로 쓰지 말 것.
- UI 버그 재현이 안 되면 파라미터 스윕 + 재현 조건을 사용자에게 조기 질의.
- #4(메모리 수정)는 trace `id` 노출 + delete/update 엔드포인트 + 인스펙터 UI가 필요 — 후속 스펙.

## 미완 / 트레이드오프
- 1400px+ 초광폭에서도 인스펙터 열리면 헤더가 아이콘만(라벨 공간 있어도). 안전·단순 택함. 필요 시 "열림 + 충분히 넓을 때만 라벨 복원"으로 다듬기.
- 스펙 021은 **미커밋**(사용자가 직접 브랜치 테스트 후 결정).
