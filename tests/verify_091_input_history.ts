/* verify_091 — 입력 히스토리 재호출 reducer 단위 검증 (스펙 091, 검증 ①).
 * 실행: node --experimental-strip-types tests/verify_091_input_history.ts
 * (의존성 0 — 순수 reducer만. 통합은 shot-input-history-091.mjs, 적대는 codex.)
 */
import {
  INITIAL_HIST,
  recallOlder,
  recallNewer,
  resetHist,
  dedupeConsecutive,
  type HistState,
} from '../admin/src/playground/inputHistory.ts'

let pass = 0
let fail = 0
function check(cond: boolean, label: string) {
  if (cond) {
    pass++
  } else {
    fail++
    console.error('  ✗ ' + label)
  }
}

const H = ['first', 'second', 'third'] // old → new

// --- 빈 히스토리: no-op, 기본 동작 양보 ---
{
  const r = recallOlder(INITIAL_HIST, [], 'draft')
  check(!r.handled && r.value === 'draft' && r.state.idx === -1, '빈 히스토리 ↑ no-op·초안 보존')
}

// --- 첫 ↑: 초안 저장 + 최신 입력 ---
{
  const r = recallOlder(INITIAL_HIST, H, 'mydraft')
  check(r.handled, '첫 ↑ handled')
  check(r.value === 'third', '첫 ↑ = 최신 입력(third)')
  check(r.state.idx === 0, '첫 ↑ idx=0')
  check(r.state.saved === 'mydraft', '첫 ↑ 초안 저장')
}

// --- 연속 ↑: 더 과거로, 최古에서 clamp ---
{
  let s: HistState = INITIAL_HIST
  let r = recallOlder(s, H, 'd')
  r = recallOlder(r.state, H, r.value) // value 인자는 비탐색일 때만 쓰임
  check(r.value === 'second' && r.state.idx === 1, '두번째 ↑ = second')
  r = recallOlder(r.state, H, r.value)
  check(r.value === 'first' && r.state.idx === 2, '세번째 ↑ = first(최古)')
  const clamped = recallOlder(r.state, H, r.value)
  check(clamped.value === 'first' && clamped.state.idx === 2, '최古 초과 ↑ = clamp(first 유지)')
  check(clamped.state.saved === 'd', 'clamp 후에도 초안 보존')
}

// --- ↓: 더 최근으로, idx0서 초안 복원 + 종료 ---
{
  // first(idx2)까지 올라간 상태 구성
  let r = recallOlder(INITIAL_HIST, H, 'draftX')
  r = recallOlder(r.state, H, r.value)
  r = recallOlder(r.state, H, r.value) // idx2 = first
  let d = recallNewer(r.state, H)
  check(d.value === 'second' && d.state.idx === 1, '↓ = second')
  d = recallNewer(d.state, H)
  check(d.value === 'third' && d.state.idx === 0, '↓ = third(최신)')
  d = recallNewer(d.state, H)
  check(d.value === 'draftX' && d.state.idx === -1, 'idx0서 ↓ = 초안 복원·탐색 종료')
  check(d.state.saved === null, '종료 시 saved 비움')
}

// --- 비탐색서 ↓: no-op ---
{
  const d = recallNewer(INITIAL_HIST, H)
  check(!d.handled && d.state.idx === -1, '비탐색 ↓ no-op')
}

// --- 탐색 중 history 축소 경합(stale idx): undefined 누출 없이 안전 클램프 ---
{
  // idx=2(H의 최古)에서 history가 1개로 줄었다 — recallNewer가 history[음수]=undefined를 내면 안 됨.
  const stale: HistState = { idx: 2, saved: 'd' }
  const d = recallNewer(stale, ['only'])
  // cur=min(2,0)=0 → 초안 복원·탐색 종료(undefined 아님).
  check(d.value === 'd' && d.state.idx === -1, 'stale idx + 축소 history ↓ = 안전 클램프(초안 복원)')
  check(d.value !== undefined, 'stale idx ↓ 값이 undefined 아님')
}
{
  // idx=3인데 history 2개 → cur=min(3,1)=1, idx=0, value=history[최신]. undefined 금지.
  const stale: HistState = { idx: 3, saved: 'x' }
  const d = recallNewer(stale, ['old', 'new'])
  check(d.value === 'new' && d.state.idx === 0, 'stale idx 부분축소 ↓ = 최신으로 클램프')
}
{
  // history가 완전히 비었어도(↓) undefined 없이 초안 복원.
  const stale: HistState = { idx: 1, saved: 'keep' }
  const d = recallNewer(stale, [])
  check(d.value === 'keep' && d.state.idx === -1, '빈 history ↓ = 초안 복원(undefined 금지)')
}

// --- saved가 빈 초안일 때 복원 ---
{
  let r = recallOlder(INITIAL_HIST, H, '') // 빈 입력서 ↑
  check(r.value === 'third' && r.state.saved === '', '빈 초안서 ↑ 진입(saved="")')
  const d = recallNewer(r.state, H)
  check(d.value === '' && d.state.idx === -1, 'idx0서 ↓ = 빈 초안 복원')
}

// --- reset ---
{
  check(resetHist().idx === -1 && resetHist().saved === null, 'reset = INITIAL')
}

// --- dedupeConsecutive: 연속만 접고 비연속 보존 ---
{
  check(JSON.stringify(dedupeConsecutive(['a', 'a', 'b'])) === JSON.stringify(['a', 'b']), '연속중복 접기')
  check(
    JSON.stringify(dedupeConsecutive(['a', 'b', 'a'])) === JSON.stringify(['a', 'b', 'a']),
    '비연속 중복 보존',
  )
  check(JSON.stringify(dedupeConsecutive([])) === JSON.stringify([]), '빈 배열')
  check(
    JSON.stringify(dedupeConsecutive(['x', 'x', 'x'])) === JSON.stringify(['x']),
    '전부 동일 → 하나',
  )
}

// --- 왕복 일관: ↑↑↓↓ 후 초안 복원, dedupe된 history와 정합 ---
{
  const raw = ['hi', 'hi', 'bye'] // 연속중복
  const h = dedupeConsecutive(raw) // ['hi','bye']
  let r = recallOlder(INITIAL_HIST, h, 'cur')
  check(r.value === 'bye', '왕복: 첫 ↑ = bye')
  r = recallOlder(r.state, h, r.value)
  check(r.value === 'hi' && r.state.idx === 1, '왕복: 두번째 ↑ = hi(접힌 뒤 최古)')
  let d = recallNewer(r.state, h)
  d = recallNewer(d.state, h)
  check(d.value === 'cur' && d.state.idx === -1, '왕복: ↓↓ 후 초안 복원')
}

console.log(`\nverify_091: ${pass} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
