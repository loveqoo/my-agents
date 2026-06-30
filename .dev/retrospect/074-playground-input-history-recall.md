# 074 — 플레이그라운드 입력 히스토리 재호출(터미널 콘솔식 ↑/↓)

> 스펙 091. 제안 #2의 *진짜* 의도(오독한 역방향 페이징 090은 파킹). Sender 입력창에서 caret이 맨앞일 때
> ↑로 과거에 보낸 입력을 거슬러 올라가고 ↓로 내려오는 셸 히스토리 모델. 순수 프런트·in-memory.

## 무엇을 했나

- **순수 reducer 분리**(`inputHistory.ts`): `recallOlder`/`recallNewer`/`resetHist`/`dedupeConsecutive`.
  정책을 순수 함수로 빼 컴포넌트(caret 판정·DOM 부수효과)와 단위테스트가 *같은 로직*을 공유(드리프트 0).
- **DebugChat 배선**: `senderRef`(GetRef<typeof Sender> — SenderRef가 최상위 export 아니라 GetRef로 추출),
  `histRef`, `history=useMemo(dedupeConsecutive(messages.filter(role==='me')))`, `onHistKey`(IME 가드 +
  caret 절대 맨앞 진입조건), Sender `ref`/`onKeyDown`/`onChange`·`onSubmit` 탐색종료.
- **히스토리 소스 = `messages` prop의 내가 보낸 입력**. 새 엔드포인트·영속 0(loadSession이 과거 세션도
  convos로 복원하므로 messages만으로 "과거 입력" 전부 손에 있음).

## 무엇이 어긋났고 무엇을 배웠나

1. **(되풀이) 의도 오독을 먼저 파킹으로 흡수.** 직전 턴에 #2를 역방향 페이징으로 읽어 스펙 090까지 썼다.
   사용자 정정 후 090을 *삭제 말고 파킹*(좋은 후속 후보)하고 091로 피벗. AskUserQuestion으로 정확히
   옵션 B("입력창서 ↑로 재호출")를 제시했으나 사용자가 첫 답으로 A를 골랐다 — **질문이 옳아도 첫 답이
   진의와 어긋날 수 있다**. 단정 전에 한 겹 더(probe-deeper)와 같은 결: 답을 받았어도 구현 전 한 번 더 모델을 공유.

2. **값 의존 effect는 값이 안 변하면 안 돈다(codex P2-1).** caret 끝 이동을 `useLayoutEffect([draft])`로
   걸었는데, 재호출 값이 현재 입력과 *같으면*(최신 입력이 이미 입력창) `setDraft`가 no-op → 리렌더 없음
   → effect 미발화 → caret 안 옮겨지고 `caretEndRef`가 true로 *남아* 다음 진짜 편집서 caret이 끝으로 튄다.
   → **단조 카운터 `recallSeq`**(재호출마다 ++)를 effect 의존으로. "이벤트마다 발화"가 필요하면 결과값이
   아니라 이벤트 카운터에 의존시켜라. → learning 093.

3. **비동기 재계산 소스에 인덱스로 접근하면 stale-idx 경합(codex P2-2).** 탐색 중 `messages` 변경으로
   `history`(useMemo)가 줄면 `histRef.idx`는 옛 스냅샷을 가리켜, `recallNewer`가 `history[음수]=undefined`를
   controlled draft로 흘려 입력창이 빈다. → 리듀서가 먼저 `cur=Math.min(idx,len-1)`로 클램프(빈 history면
   초안 복원·종료). `recallOlder`는 기존 `Math.min`으로 이미 안전. → learning 093에 합침.

4. **브라우저 테스트 셋업도 같은 함정.** P2-1 회귀 단언이 처음 실패 — 직전 단계가 navigating 상태를
   남겼고 **동일 값 `fill`은 onChange 미발화**라 탐색 리셋이 안 됐다. `fill('')→fill(값)`으로 강제 리셋해
   해결. 제품 버그 아닌 테스트 artifact였지만, "값이 같으면 변경 이벤트가 안 온다"는 P2-1과 같은 뿌리.

## 검증 사다리 3런(비겹침)

- ① **단위**(`verify_091`, node --experimental-strip-types): 28 passed. 빈/단일·연속 ↑ clamp·↓ 초안복원·
  dedupe 경계·왕복 + **stale-idx 축소 경합 방어**(undefined 누출 0).
- ② **브라우저**(Playwright 시스템 Chrome, `HIST091_OK`, 12단언): ↑/↓ 재호출·편집종료·caret-맨앞-아니면
  미재호출 음성단언 + **값 동일 재호출서도 caret 끝 이동**(P2-1 회귀).
- ③ **적대 codex**: P2 2건 발견 → 수정 → 재확인 "No P1/P2 findings". 세 런이 잡은 결함이 안 겹침
  (단위=리듀서 시맨틱, 브라우저=DOM/caret 실동작, codex=값의존 effect·경합 같은 *상상 못한* 표면).

## 다음에 적용

- **caret/포커스 같은 명령형 DOM 부수효과를 effect로 걸 땐 의존 배열을 의심**: 값 의존이면 "값이 안 변하면
  안 돈다"를 항상 자문. 이벤트마다 필요하면 카운터.
- **비동기로 재계산되는 리스트(useMemo/쿼리)에 보존한 인덱스로 접근하면 항상 경합** — 리듀서/접근부에서
  현재 길이로 클램프하거나 스냅샷.
- 8항목 제안 진행: #2 완료. 다음은 #3(원시 블록 응답 숨김) — 순서대로.
