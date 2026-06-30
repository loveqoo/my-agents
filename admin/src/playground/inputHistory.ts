/* 입력 히스토리 재호출 — 터미널 콘솔 방식 ↑/↓ (스펙 091).
 *
 * 정책을 순수 함수로 분리해 컴포넌트(DebugChat)와 단위테스트가 *같은 로직*을 공유한다(드리프트 0).
 * 컴포넌트는 caret 판정·DOM 부수효과만 담당하고, "무엇을 보여줄지"는 전적으로 여기서 결정한다.
 *
 * history: 시간순(old→new), dedupeConsecutive로 *연속* 중복이 접힌 배열.
 * state.idx: -1 = 비탐색(라이브 초안). 0 = 가장 최근 과거 입력, 커질수록 더 오래된 입력.
 * state.saved: 탐색 진입 시 스택해 둔 라이브 초안(↓로 끝까지 내려오면 복원).
 */

export type HistState = { idx: number; saved: string | null }

export const INITIAL_HIST: HistState = { idx: -1, saved: null }

export type HistStep = { state: HistState; value: string; handled: boolean }

/** ↑ — 더 오래된 입력으로. 비탐색이면 현재 value를 saved에 스택하고 최신(idx 0)부터. */
export function recallOlder(state: HistState, history: string[], value: string): HistStep {
  if (history.length === 0) return { state, value, handled: false }
  const saved = state.idx === -1 ? value : state.saved
  const idx = state.idx === -1 ? 0 : Math.min(state.idx + 1, history.length - 1)
  return { state: { idx, saved }, value: history[history.length - 1 - idx], handled: true }
}

/** ↓ — 더 최근으로. idx 0에서 한 번 더 내려오면 saved(라이브 초안) 복원하고 탐색 종료.
 *  탐색 중 messages 변경으로 history가 줄어 idx가 범위를 벗어났을 수 있어(경합) 먼저 클램프 —
 *  안 그러면 history[음수] = undefined가 controlled draft로 새어 입력창이 빈다. */
export function recallNewer(state: HistState, history: string[]): HistStep {
  if (state.idx === -1) return { state, value: '', handled: false }
  const cur = Math.min(state.idx, history.length - 1) // 줄어든 history에 맞춰 현재 위치 보정
  if (cur <= 0) {
    return { state: INITIAL_HIST, value: state.saved ?? '', handled: true }
  }
  const idx = cur - 1
  return { state: { idx, saved: state.saved }, value: history[history.length - 1 - idx], handled: true }
}

/** 사용자 편집·전송 시 탐색 종료. */
export function resetHist(): HistState {
  return INITIAL_HIST
}

/** 연속 동일값만 접는다(bash HISTCONTROL=ignoredups). 비연속 중복은 진짜 과거라 보존. */
export function dedupeConsecutive(texts: string[]): string[] {
  const out: string[] = []
  for (const t of texts) {
    if (out.length === 0 || out[out.length - 1] !== t) out.push(t)
  }
  return out
}
