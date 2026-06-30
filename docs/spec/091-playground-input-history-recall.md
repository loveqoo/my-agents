# 091 — 플레이그라운드 입력 히스토리 재호출 (터미널 콘솔 방식 ↑/↓)

> 보고(#2, 정정): "유저 채팅 컴포넌트에서 **커서가 맨 앞에 있을 때 ↑ 키**를 누르면 과거에 입력했던
> 입력을 입력창에 로드." 사용자 확인: "터미널 콘솔 히스토리 방식과 비슷하겠네요." → ↑로 과거 입력을
> 거슬러 올라가고, ↓로 내려오고, 편집하면 빠져나오는 **셸 히스토리** 모델.
> 관련: 본 스펙이 8항목 #2의 *진짜* 의도. 오독에서 나온 역방향 페이징은 spec 090(파킹).
> 참고 자산: learning 083(Playground cross-tab 소비표면)·retrospect 045(세션 이어가기 비동기) — 동일
> Playground/DebugChat 입력 표면, 단 본건은 **순수 프런트·in-memory**라 백엔드/RBAC 무관.

## 배경 — 측정한 현황

- **입력창 = antd-x `Sender`**(`DebugChat.tsx:813`): `value={draft}`/`onChange={setDraft}`/`onSubmit`(clear+onSend).
  `SenderProps.onKeyDown?: (e) => void | false`(false=기본동작 취소) 지원. `SenderRef.inputElement` =
  내부 `HTMLTextAreaElement`(caret `selectionStart/End`·`setSelectionRange` 접근 가능). → **순수 프런트로 충분**.
- **히스토리 소스 = 현재 대화의 *내가 보낸* 입력**: `send`(`Playground.tsx:172`)가 convos에 `{role:'me', text}`
  적층. 과거 세션을 열면 `loadSession`이 DB 메시지를 convos로 복원(역시 role 'me' 포함). 즉 `messages`
  prop만으로 "과거에 입력했던 입력" 전부가 손에 있다 — **새 엔드포인트·영속 0**.
- **JS 테스트 러너 없음**(vite만). 단 Node v24라 `node --experimental-strip-types`로 .ts 직접 실행 →
  순수 reducer 단위 테스트 의존성 0. 통합은 Playwright(시스템 Chrome) 기존 셋업 재사용.

## 결정

- **터미널 히스토리 모델.** ↑ = 더 오래된 입력, ↓ = 더 최근/초안 복원. **진입 조건**: 비탐색 상태에서
  `↑`이고 **caret이 입력 절대 맨 앞**(`selectionStart===0 && selectionEnd===0`)일 때만 재호출 시작(그 외엔
  멀티라인 위 이동 등 기본 동작 보존). **일단 탐색 진입하면** ↑/↓는 caret 위치와 무관히 더 오래/더 최근으로 이동.
  **편집(onChange) 또는 전송 시 탐색 종료**(idx=-1). 재호출 시 caret은 **끝**으로(편집 자연스럽게).
- **순수 reducer 분리.** 키 핸들링 정책을 `inputHistory.ts`의 순수 함수로 빼 컴포넌트와 단위테스트가
  *같은 로직*을 공유(드리프트 0). DebugChat은 caret 판정·DOM 부수효과만 담당.
- **연속 중복 접기**(bash `HISTCONTROL=ignoredups`식). 같은 입력을 연달아 보냈을 때 ↑가 같은 값을 반복하지
  않게 history 구성 시 *연속* 동일값만 collapse(비연속 중복은 보존 — 진짜 과거니까).
- **IME 가드.** 한글 조합 중(`e.nativeEvent.isComposing`)엔 가로채지 않음(조합 깨짐 방지).
- **in-memory·세션 로컬.** 새로고침 넘어 영속(localStorage)은 비목표 — 대화 컨텍스트 내 재호출이면 충분.

## 설계

### 1. 순수 reducer (`admin/src/playground/inputHistory.ts`)

```
type HistState = { idx: number; saved: string | null }   // idx -1 = 비탐색(라이브 초안)
const INITIAL: HistState = { idx: -1, saved: null }

// history: 시간순(old→new), 연속중복 접힌 배열. value: 현재 입력값.
recallOlder(state, history, value): { state, value, handled }
  - history 비면 handled=false (기본 동작 양보)
  - idx===-1 → saved=value, idx=0 ; else idx=min(idx+1, len-1)
  - value = history[len-1-idx]  (idx 0 = 최신) ; handled=true
recallNewer(state, history): { state, value, handled }
  - idx===-1 → handled=false
  - idx>0 → idx-1, value=history[len-1-idx], handled=true
  - idx===0 → idx=-1, value=saved ?? '', handled=true (초안 복원·종료)
reset(): INITIAL
dedupeConsecutive(texts): string[]   // 연속 동일값 collapse
```

### 2. 컴포넌트 배선 (`DebugChat.tsx`)

- `senderRef = useRef<SenderRef>(null)`, `histRef = useRef<HistState>(INITIAL)`, `caretEndRef = useRef(false)`.
- `history = useMemo(() => dedupeConsecutive(messages.filter(m => m.role === 'me').map(m => m.text)), [messages])`.
- Sender에 `ref={senderRef}` + `onKeyDown={onHistKey}`:
  - `isComposing` → return(양보).
  - `ArrowUp`: 비탐색이면 caret 맨앞(`inputElement.selectionStart===0 && ===selectionEnd`) 아닐 시 return.
    `recallOlder` handled → `setDraft(value)`, `histRef=state`, `caretEndRef=true`, `e.preventDefault()`, `return false`.
  - `ArrowDown`: 비탐색이면 return. `recallNewer` handled → 동일 처리.
  - 그 외 키 → 기본.
- `onChange(v)`: `histRef.current = reset()` 후 `setDraft(v)` — 사용자 편집 시 탐색 종료(우리 재호출은
  setDraft 직접 호출이라 onChange 미발화 → 사용자 입력만 잡힘).
- `onSubmit(text)`: `histRef.current = reset()`, `setDraft('')`, `onSend(text)`.
- caret 끝 이동: `useLayoutEffect(() => { if (caretEndRef.current) { const ta = senderRef.current?.inputElement;
  if (ta) ta.setSelectionRange(ta.value.length, ta.value.length); caretEndRef.current=false } }, [draft])`.

### 3. 표면/접근성 (선택)

- placeholder 또는 footer 힌트에 "↑ 이전 입력" 한 줄(비강제, 발견성↑). 과한 금칠 금지 — 핵심은 키 동작.

## 검증 사다리 3런 (비겹침)

- ① **단위 시맨틱**: `tests/verify_091_input_history.ts`(`node --experimental-strip-types`) — reducer 순수
  검증: 빈 히스토리 no-op·첫 ↑가 초안 저장+최신·연속 ↑가 최古에서 clamp·↓가 더 최근·idx0서 ↓가 초안
  복원+종료·dedupeConsecutive(연속만 접고 비연속 보존)·왕복 일관.
- ② **브라우저 통합**: Playwright(시스템 Chrome) `tests/browser/shot-input-history-091.mjs` — 실제 Playground:
  입력 2~3개 전송→입력창 비움→caret 맨앞 ↑=직전 입력·다시 ↑=더 과거·↓=더 최근·타이핑 시 탐색 종료·
  **caret이 맨앞 아닐 때 ↑는 재호출 안 함**(기본 caret 이동) 음성 단언. 출력 `HIST091_OK`.
- ③ **적대 타자(codex)**: reducer+핸들러의 "보장 목록 여집합" — IME 조합, 멀티라인 진입조건, caret 복원
  타이밍, 초안 복원 정확성, dedupe 경계, 빈/단일 히스토리, 탐색 중 외부 setDraft 경합.

## 완료 기준 (측정 가능)

- [x] `inputHistory.ts` 순수 reducer + `dedupeConsecutive`.
- [x] DebugChat Sender `ref`+`onKeyDown`+`onChange`/`onSubmit` 탐색종료+caret 끝 이동 배선.
- [x] `verify_091_input_history.ts` GREEN(28 passed — 단위 케이스 + stale-idx 경합 방어).
- [x] 브라우저 `HIST091_OK`(12단언): ↑/↓ 재호출·편집 종료·caret-맨앞-아니면 미재호출 + **값 동일 재호출서도 caret 끝 이동**(P2 회귀).
- [x] **admin tsc 0**, 무회귀, 적대 codex 통과(P2 2건 수정 후 재확인 클린).

### 적대 리뷰(codex)에서 잡혀 수정한 P2 2건

1. **caret 끝 이동이 no-op setDraft에서 미발화** — `useLayoutEffect([draft])`는 재호출 값이 현재 입력과
   같으면(예: 최신 입력이 이미 입력창) 리렌더가 안 일어나 안 돈다. 게다가 `caretEndRef`가 true로 남아
   다음 *진짜* 편집에서 caret이 끝으로 튄다. → caret effect 의존을 **단조 카운터 `recallSeq`**(재호출마다 ++)로
   바꿔 값 동일성과 무관히 발화시키고 `caretEndRef`를 제거. (값에 의존하는 effect는 "값이 안 변하면 안 돈다".)
2. **탐색 중 history 축소 경합** — 탐색 중 `messages` 변경으로 `history`가 줄면 stale `idx`가 범위를 벗어나
   `recallNewer`가 `history[음수]=undefined`를 controlled draft로 흘려 입력창이 빈다. → `recallNewer`가
   먼저 `cur = Math.min(idx, len-1)`로 클램프(빈 history면 초안 복원·종료). `recallOlder`는 기존 `Math.min`
   클램프로 이미 안전.

## 비목표

- 새로고침 넘은 영속(localStorage)·cross-세션 전역 히스토리. ↓ 자동완성/검색(Ctrl-R식). 백엔드/스키마 변경.
- spec 090(역방향 페이징)은 별개 파킹 항목 — 본 스펙과 무관.
