/* 스펙 333+337 기능 e2e — 검색 히트에서 즉시 편집(정밀 진입, ordinal 좌표).
   행 데이터는 **객체 data**로 — 스펙 337 회귀: 객체 data 행은 히트 텍스트(평탄화)가 원본 JSONL에
   없어 텍스트 매칭이 항상 실패("전체가 나옴" 사용자 보고). ordinal 줄 좌표가 처방.
   H1) 검색 시험 드로어 → 히트 편집 버튼 → 에디터가 **그 JSONL 줄 전체가 선택된 채** 열림
   H2) 그 행 교정 → 저장 → 부분 재임베딩 토스트
   H3) 재검색 → 교정된 내용이 히트로(기능 왕복 — 검색→편집→검색)
   실행: PLAYWRIGHT_DIR=<abs playwright dir> node tests/browser/verify-hit-edit-333.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const S = Math.random().toString(36).slice(2, 8)
const COL = `e2e-333-${S}`

const fails = []
const ok = (cond, msg) => {
  console.log((cond ? '  ok  ' : ' FAIL ') + msg)
  if (!cond) fails.push(msg)
}
// 객체 data 행(스펙 337) — 임베딩 텍스트는 "title: …\ndesc: …" 평탄화라 원문에 부재.
const row = (id, title, desc) => JSON.stringify({ metadata: { id }, data: { title, desc } })
const R2_TITLE = '헤어질 결심'
const R2_NEWDESC = '산과 바다, 형사 해준과 서래의 붕괴와 미결, 2022년 박찬욱 감독.'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1360, height: 950 } })).newPage()
let cid = null

try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').waitFor({ timeout: 15000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  const models = await (await page.request.get(`${API}/models`)).json()
  const emb = models.find((m) => m.kind === 'embedding')
  cid = (await (await page.request.post(`${API}/collections`, {
    data: { name: COL, kind: 'entity', embedding_model_id: emb.id },
  })).json()).id
  const upRes = await page.request.post(`${API}/collections/${cid}/documents`, {
    multipart: { file: { name: 'movies.jsonl', mimeType: 'application/jsonl',
      buffer: Buffer.from(`${row(1, '기생충', '두 가족의 계급 우화, 2019년 칸 황금종려상.')}\n${row(2, R2_TITLE, '형사와 용의자의 미묘한 감정, 2022년.')}`) } },
  })
  ok(upRes.status() === 201, `준비: 업로드 접수 (${upRes.status()})`)
  // 배경 인제스트(스펙 334) ready 대기
  for (let i = 0; i < 40; i++) {
    const d = (await (await page.request.get(`${API}/collections/${cid}/documents`)).json()).items[0]
    if (d && d.status === 'ready') break
    await new Promise((r) => setTimeout(r, 500))
  }

  // H1 — 검색 드로어 → 질의 → 히트 편집 버튼 → 에디터(해당 JSONL 줄 전체 선택)
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(800)
  await page.getByRole('tab', { name: '엔티티 임베딩' }).click()
  await page.waitForTimeout(400)
  const colRow = page.locator('tr', { hasText: COL }).first()
  await colRow.getByRole('button', { name: '검색' }).click()
  await page.getByText(`검색 시험 · ${COL}`).waitFor({ timeout: 8000 })
  const drawer = page.locator('.ant-drawer-section', { hasText: '검색 시험 ·' })
  await drawer.getByPlaceholder(/환불 정책/).fill(`${R2_TITLE} 형사와 용의자의 감정`)
  await drawer.getByRole('button', { name: '검색' }).click()
  await drawer.getByText(/결과 \d+건/).waitFor({ timeout: 15000 })
  // 최상위 히트가 2번 행인지 확인 후 그 카드의 편집 버튼(첫 카드=첫 anticon-edit)
  await drawer.locator('.anticon-edit').first().click()
  await page.getByText('문서 편집 · movies.jsonl').waitFor({ timeout: 8000 })
  await page.locator('.cm-content').waitFor({ timeout: 8000 })
  await page.waitForTimeout(600)
  const selected = await page.evaluate(() => window.getSelection()?.toString() ?? '')
  // 스펙 337: 선택은 ordinal 좌표의 JSONL **줄 전체** — metadata id와 데이터 필드가 함께 있어야.
  ok(selected.includes('"id":2') && selected.includes(R2_TITLE),
     `H1 히트 행(줄 전체)이 선택된 채 열림 (sel=${selected.slice(0, 60)}…)`)

  // H2 — 선택된 줄을 교정 행으로 교체 → 저장
  await page.keyboard.insertText(row(2, R2_TITLE, R2_NEWDESC))
  await page.getByRole('button', { name: '저장', exact: true }).click()
  await page.locator('.ant-message').getByText(/저장 완료 — 청크 2개 \(재임베딩 1 · 재사용 1\)/).waitFor({ timeout: 15000 })
  ok(true, 'H2 저장 토스트(재임베딩 1·재사용 1)')

  // H3 — 재검색으로 교정 반영(기능 왕복). 동일 텍스트 질의(평탄화형)로 결정화.
  const sr = await (await page.request.post(`${API}/collections/${cid}/search`,
    { data: { query: `title: ${R2_TITLE}\ndesc: ${R2_NEWDESC}`, top_k: 2 } })).json()
  ok(sr.results?.[0]?.text?.includes('박찬욱'), `H3 교정 내용이 검색 최상위 (got ${sr.results?.[0]?.text?.slice(0, 40)}…)`)
  ok(sr.results?.[0]?.ordinal != null, 'H3b 히트에 ordinal 동반')
} finally {
  if (cid) {
    const delRes = await page.request.delete(`${API}/collections/${cid}`).catch(() => null)
    console.log(`CLEANUP (${delRes?.status?.() ?? 'skip'})`)
  }
  await browser.close()
}

console.log()
if (fails.length) {
  console.log(`FAILED ${fails.length}건: ${fails.join(' | ')}`)
  process.exit(1)
}
console.log('VERIFY337_UI_OK — 객체 data 행: 히트→줄 좌표 선택→교정→재검색 반영 관통')
