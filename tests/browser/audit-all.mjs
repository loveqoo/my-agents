/* 스펙 169 — 전수 UI 감사 오케스트레이터. 기계적 harness 3종을 순차 실행하고 종합 판정한다.
   "지속적 발견"을 한 명령으로 — 수동/CI/자율 루프 어디든. 종합 종료코드 = 하나라도 FAIL이면 1.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/audit-all.mjs

   카피 축(축3)은 에이전트 구동이라 여기 없음 — deep-reasoner + tests/copy-rubric.md로 별도 실행. */
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const pwDir = process.env.PLAYWRIGHT_DIR ?? `${process.cwd()}/tests/e2e/node_modules/playwright`

const HARNESSES = [
  { key: 'screens', desc: '화면 오버플로(축2)', script: 'tests/browser/ui-audit.mjs', args: ['tests/browser/out-ui-audit'] },
  { key: 'overlays', desc: '드로어·모달 오버플로(축2 확장)', script: 'tests/browser/ui-audit-overlays.mjs', args: ['tests/browser/out-overlay'] },
  { key: 'scenario', desc: '사용 시나리오(축1)', script: 'tests/browser/scenario-audit.mjs', args: ['tests/browser/out-scenario', String(Date.now() % 1_000_000)] },
]

async function reachable(u) {
  try { await fetch(u, { method: 'GET', signal: AbortSignal.timeout(3000) }); return true } catch { return false }
}

console.log('=== 전수 UI 감사 (스펙 169) ===')
// 프리플라이트 — 서버 down을 정직히 보고(감사가 빈 화면을 초록으로 오판 방지).
const viteUp = await reachable(URL)
const apiUp = await reachable(API)
console.log(`  vite ${URL}: ${viteUp ? 'up' : 'DOWN'} · api ${API}: ${apiUp ? 'up' : 'DOWN'}`)
if (!viteUp || !apiUp) {
  console.error('  ✗ dev 서버가 떠 있지 않습니다 — 감사 중단(빈 화면을 통과로 오판하지 않게).')
  process.exit(2)
}
if (!existsSync(pwDir)) { console.error(`  ✗ PLAYWRIGHT_DIR 없음: ${pwDir}`); process.exit(2) }

const results = []
for (const h of HARNESSES) {
  console.log(`\n──── ${h.key} · ${h.desc} ────`)
  const r = spawnSync('node', [h.script, ...h.args], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PLAYWRIGHT_DIR: pwDir },
    encoding: 'utf8',
    timeout: 600_000,
  })
  const out = (r.stdout || '') + (r.stderr || '')
  // 각 harness의 종합 라인만 요약(FAIL n / PASS)·전체는 out-*/scorecard.json에.
  const summary = out.split('\n').filter((l) => /FAIL|PASS|스코어카드|막힘|blocked|=== /.test(l)).slice(-6)
  console.log(summary.map((l) => '  ' + l.trim()).join('\n'))
  const code = r.status ?? (r.error ? 1 : 0)
  results.push({ key: h.key, desc: h.desc, code, ok: code === 0 })
}

console.log('\n================ 종합 ================')
for (const r of results) console.log(`  ${r.ok ? ' ok ' : 'FAIL'}  ${r.key.padEnd(9)} ${r.desc}`)
const failed = results.filter((r) => !r.ok)
console.log(`\n기계 감사 ${results.length}종 중 FAIL ${failed.length}`)
console.log('카피 축(축3): deep-reasoner + tests/copy-rubric.md로 별도 실행(기계화 불가).')
console.log('상세: tests/browser/out-*/scorecard.json · 스크린샷 out-*/{viewport}/*.png')
process.exit(failed.length ? 1 : 0)
