/* 스펙 335 기능 e2e — 배경 인제스트 이벤트 전역 알림.
   핵심 단언: **문서 드로어를 열지 않은 채**(에이전트 메뉴에 머문 상태) 업로드 →
   E1) 성공: "임베딩 완료" notification(파일명·청크 수)
   E2) 실패(깨진 PDF): "인제스트 실패" notification(사유)
   — 폴링(드로어 한정)이 아니라 SSE 전역 구독이 동작함을 실측.
   실행: PLAYWRIGHT_DIR=<abs playwright dir> node tests/browser/verify-ingest-events-335.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const S = Math.random().toString(36).slice(2, 8)
const COL = `e2e-335-${S}`

const fails = []
const ok = (cond, msg) => {
  console.log((cond ? '  ok  ' : ' FAIL ') + msg)
  if (!cond) fails.push(msg)
}
const row = (id, data) => JSON.stringify({ metadata: { id }, data })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1360, height: 950 } })).newPage()
let cid = null

try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 }) // SSE 상시 연결로 networkidle 불성립(스펙 335)
  await page.getByPlaceholder('you@example.com').waitFor({ timeout: 15000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(1500) // EventSource 연결 안정화

  const models = await (await page.request.get(`${API}/models`)).json()
  const emb = models.find((m) => m.kind === 'embedding')
  cid = (await (await page.request.post(`${API}/collections`, {
    data: { name: COL, kind: 'entity', embedding_model_id: emb.id },
  })).json()).id

  // E1 — 에이전트 메뉴에 머문 채 업로드(드로어 없음) → 전역 성공 알림
  await page.request.post(`${API}/collections/${cid}/documents`, {
    multipart: { file: { name: 'notify.jsonl', mimeType: 'application/jsonl', buffer: Buffer.from(`${row(1, '알림 검증 행 하나')}\n${row(2, '알림 검증 행 둘')}`) } },
  })
  const okNote = page.locator('.ant-notification').getByText(/임베딩 완료/)
  await okNote.waitFor({ timeout: 20000 })
  const body = await page.locator('.ant-notification').innerText()
  ok(body.includes('notify.jsonl') && body.includes('2개'), `E1 전역 성공 알림(파일명+청크 수) — "${body.replace(/\n/g, ' ').slice(0, 80)}"`)

  // E2 — 깨진 PDF(문서형 컬렉션) → 전역 실패 알림
  const dcol = (await (await page.request.post(`${API}/collections`, {
    data: { name: `${COL}-doc`, kind: 'document', embedding_model_id: emb.id },
  })).json()).id
  await page.request.post(`${API}/collections/${dcol}/documents`, {
    multipart: { file: { name: 'broken.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not-a-pdf') } },
  })
  await page.locator('.ant-notification').getByText(/인제스트 실패/).waitFor({ timeout: 20000 })
  const body2 = await page.locator('.ant-notification').innerText()
  ok(body2.includes('broken.pdf'), `E2 전역 실패 알림(파일명+사유) — "${body2.replace(/\n/g, ' ').slice(0, 80)}"`)
  await page.request.delete(`${API}/collections/${dcol}`).catch(() => null)
} finally {
  if (cid) await page.request.delete(`${API}/collections/${cid}`).catch(() => null)
  console.log('CLEANUP done')
  await browser.close()
}

console.log()
if (fails.length) {
  console.log(`FAILED ${fails.length}건: ${fails.join(' | ')}`)
  process.exit(1)
}
console.log('VERIFY335_UI_OK — 드로어 없이도 전역 알림(성공·실패) 수신')
