/* 스펙 435 FE 검증 — 실패 문서 재시도 버튼 + 진행률 표기.
   준비(DB 직접): 컬렉션+실패(error) 문서를 심고 → 브라우저에서 재시도 클릭 → 완료 확인.
   실행: PLAYWRIGHT_DIR=tests/e2e/node_modules/playwright node tests/browser/verify-435-retry-progress.mjs */
import fs from 'node:fs'
import { execFileSync } from 'node:child_process'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'
fs.mkdirSync(OUT, { recursive: true })

// ── 픽스처: 실패 문서 1개(원본 보존) 심기 ──
const seed = execFileSync('uv', ['run', 'python', '-c', `
import asyncio, sys, uuid
sys.path.insert(0, "packages/api/src")
from sqlalchemy import select
from api.db import SessionLocal
from api.models import Collection, Document, DocumentBlob, ModelConfig
async def main():
    async with SessionLocal() as s:
        emb = (await s.execute(select(ModelConfig).where(ModelConfig.name=="mock-embed"))).scalar_one()
        name = "v435-ui-" + uuid.uuid4().hex[:6]
        c = Collection(name=name, kind="document", embedding_model_id=emb.id,
                       dims=1024, chunk_size=200, chunk_overlap=40, status="ready")
        s.add(c); await s.commit()
        data = ("재시도 UI 검증 본문입니다. " * 400).encode()
        d = Document(collection_id=c.id, filename="retry-ui.txt", content_type="text/plain",
                     status="error", error="일시 실패(픽스처 주입)", byte_size=len(data))
        s.add(d); await s.commit()
        s.add(DocumentBlob(document_id=d.id, data=data)); await s.commit()
        print(name)
asyncio.run(main())
`], { encoding: 'utf8', cwd: process.cwd() }).trim().split('\n').pop()
console.log('픽스처 컬렉션:', seed)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 900 } })).newPage()
const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForTimeout(1200)
  if (await page.getByText('my-agents 로그인', { exact: true }).isVisible().catch(() => false)) {
    await page.getByPlaceholder('you@example.com').fill(EMAIL)
    await page.getByPlaceholder('비밀번호').fill(PASSWORD)
    await page.getByRole('button', { name: '로그인' }).click()
    await page.waitForTimeout(1500)
  }
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  await page.getByText(seed, { exact: false }).first().click()   // 드로어 열기
  await page.waitForTimeout(1200)
  ok(await page.getByText('오류', { exact: false }).first().isVisible(), '① 실패 문서가 오류 상태로 보임')
  await page.screenshot({ path: `${OUT}/v435-before.png` })

  // 재시도 버튼(reload 아이콘) 클릭 — 삭제(danger) 아닌 버튼
  const row = page.locator('tr', { hasText: 'retry-ui.txt' }).first()
  const btns = row.locator('button')
  const n = await btns.count()
  let clicked = false
  for (let i = 0; i < n; i++) {
    const cls = (await btns.nth(i).getAttribute('class')) || ''
    if (cls.includes('dangerous')) continue           // 삭제 버튼 제외
    const html = await btns.nth(i).innerHTML()
    if (html.includes('anticon-reload') || html.includes('reload')) {
      await btns.nth(i).click(); clicked = true; break
    }
  }
  ok(clicked, '② 재시도 버튼 발견·클릭')
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}/v435-after-click.png` })

  // 재시도 후: 처리 중(파싱/임베딩) 또는 완료로 전이 — 최대 40초 폴링
  let done = false
  for (let i = 0; i < 40; i++) {
    const body = await page.locator('body').innerText()
    if (body.includes('완료')) { done = true; break }
    await page.waitForTimeout(1000)
  }
  ok(done, '③ 재시도 후 문서가 완료 상태로 전이(재업로드 없이)')
  await page.screenshot({ path: `${OUT}/v435-done.png` })

  console.log(fails.length ? `\nFAIL ${fails.length}` : '\nVERIFY435_UI_OK')
  process.exitCode = fails.length ? 1 : 0
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: `${OUT}/v435-debug.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
