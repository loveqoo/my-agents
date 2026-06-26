# 023 — Playground userId를 인증 주체에서 도출(수동 입력 제거)

지배 스펙: [docs/spec/032](../../docs/spec/032-playground-userid-from-auth-principal.md)
날짜: 2026-06-26 · 브랜치: `feat/agent-service`(main 머지 금지)

## 한 일

031로 세션 쿠키 인증이 생겨 "인증 주체"가 서버에 존재하게 되자, Playground가 따로 받던
**mem0 user_id 축 수동 입력을 제거**하고 인증 주체에서 도출하도록 통합했다.
- `chat()` 핸들러에 `principal=Depends(current_principal)` 주입(라우터 게이트와 같은 콜러블이라
  FastAPI가 중복 제거). `user_id = None if isinstance(principal, str) else str(principal.id)` —
  쿠키 유저는 안정 UUID, 머신 토큰("machine" 센티넬)은 None(세션 단기 폴백, 기존 빈 userId와 동일).
- `ChatRequest.userId` 필드 + `_clean_user_id` validator 제거. 3개 사용처(recall/add scope·_persist)
  와 `_remote_stream` 인자를 도출 값으로 치환.
- 프론트: 헤더 AutoComplete·state·prop·잠금 제거, `streamChat`에서 userId 전송 제거.
  "새 대화"는 userId 잠금에서 분리해 `canResetConversation`(대화가 있을 때만)으로 격하.

## 잘된 것

- **타자 2종이 또 수렴했다.** codex와 독립 서브에이전트 둘 다 SHIP, HIGH/MED 0. 둘 다 독립적으로
  `streamChat`의 *두 번째 호출자*(`Chat.tsx`, positional 4인자)가 시그니처 변경에 무영향임을 짚었고,
  codex는 tsc까지 자체 실행했다. 022의 교훈("사이드 깊은 변경은 타자 2종 병렬") 그대로 적용 → 신뢰.
  [[dont-skip-context-recall-learnings]]
- **수치/상태로 끊어 라이브 검증.** trace의 `memoryScope.user_id`를 로그인 UUID와 **문자열 비교**로
  일치 확인(쿠키 경로), 머신 경로는 user_id 축 *부재*로 확인. 추상적 "잘 되는 것 같다"가 아니라
  관측 가능한 값으로 끊었다. [[numeric-verification-unlocks-autonomy]]
- **브라우저 선제 캡처.** 사용자 스샷 안 기다리고 Playwright+시스템Chrome으로 헤더(입력 0)·채팅·리셋
  3컷. 마침 첫 에이전트가 code(SDK) 에이전트라 `_remote_stream` 경로까지 자동 커버됐다.
  [[verify-ui-in-browser-proactively]]

## 막힌 것 / 교훈

- **"마지막 소비처" 단정의 함정.** 스펙 초안에서 `listUserIds`를 "Playground가 유일 소비처 →
  죽은 코드"로 적고 제거했다가, tsc가 `MemoryView.tsx`(어드민 유저-메모리 탭)의 두 번째 소비처를
  잡아냈다. 제거를 되돌려 존치. **"이게 마지막 사용처"는 grep로 전수 확인하기 전엔 단정 금지** —
  "지우기 전에 대상을 본다"와 같은 결. [[probe-deeper-before-concluding]]
- **검증을 위해 사용자 dev 서버를 재기동했다(부수효과).** 기존 서버가 `--reload` 없이 구버전 코드를
  들고 있어, `--reload` + 테스트용 `API_AUTH_TOKEN` + `verify032` 시드 admin으로 재기동했다.
  사용자의 원래 launch env(특히 API_AUTH_TOKEN 값)를 덮었고 DB에 테스트 superuser가 1명 남았다.
  → 다음엔 검증 전 **현 프로세스 env를 (마스킹해) 먼저 보존**하거나, 사용자에게 재기동 가부를 한 번
  확인하는 편이 덜 침습적. 남은 `verify032`는 throwaway로 명시하고 정리는 사용자 선택에 맡김.

## 적용점(다음 작업 Context에서 상기)

- 클라이언트가 보내던 식별자를 **서버 인증 주체로 도출**하면 스푸핑 표면이 사라진다(엄격히 더 안전).
  비슷한 "클라가 보내는 신원/스코프 키"가 또 있으면 같은 패턴으로 좁힌다.
- positional 파라미터를 **중간에서** 제거할 땐 전 호출처를 grep — 꼬리 인자만 보던 호출자는
  무사하지만, sessionId 뒤에 overrides를 positional로 넘기던 호출자는 밀려 깨질 수 있다(이번엔 안전).
- dev 서버 재기동이 필요한 검증은 **env 보존 → 재기동 → 복구** 또는 사용자 확인을 절차화.
