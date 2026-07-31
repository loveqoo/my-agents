/* 스펙 436 FE 검증 — 재인덱싱 완료가 우하단 알림으로 뜬다. */
import fs from 'node:fs'
import { execFileSync } from 'node:child_process'
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${process.cwd()}/${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? 'tests/browser/out-tmp'
fs.mkdirSync(OUT, { recursive: true })
// 픽스처: ready 컬렉션+문서 1개(재인덱싱 대상)
const name = execFileSync('uv', ['run', 'python', '-c', `
import asyncio, sys, uuid
sys.path.insert(0, "packages/api/src")
from sqlalchemy import select
from api.db import SessionLocal
from api.models import Collection, Document, DocumentBlob, Chunk, ModelConfig
async def main():
    async with SessionLocal() as s:
        emb=(await s.execute(select(ModelConfig).where(ModelConfig.name=="mock-embed"))).scalar_one()
        n="v436-ui-"+uuid.uuid4().hex[:6]
        c=Collection(name=n,kind="document",embedding_model_id=emb.id,dims=1024,chunk_size=300,chunk_overlap=50,status="ready",doc_count=1,chunk_count=1)
        s.add(c); await s.commit()
        data=("재인덱싱 알림 검증. "*200).encode()
        d=Document(collection_id=c.id,filename="n436.txt",content_type="text/plain",status="ready",byte_size=len(data),chunk_count=1)
        s.add(d); await s.commit()
        s.add(DocumentBlob(document_id=d.id,data=data))
        s.add(Chunk(document_id=d.id,collection_id=c.id,ordinal=0,text="x",meta=None,embedding=[0.0]*1024))
        await s.commit(); print(n)
asyncio.run(main())
`], { encoding: 'utf8' }).trim().split('\n').pop()
console.log('픽스처:', name)
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 900 } })).newPage()
const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
try {
  await page.goto(URL, { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(1200)
  if (await page.getByText('my-agents 로그인', { exact: true }).isVisible().catch(() => false)) {
    await page.getByPlaceholder('you@example.com').fill(_fx.email)
    await page.getByPlaceholder('비밀번호').fill(_fx.password)
    await page.getByRole('button', { name: '로그인' }).click(); await page.waitForTimeout(1500)
  }
  // 재인덱싱은 API로 트리거(쿠키는 브라우저 컨텍스트에 있으니 page.request 사용)
  const cols = await (await page.request.get('http://127.0.0.1:8000/collections')).json()
  const col = cols.find((c) => c.name === name)
  ok(!!col, '① 픽스처 컬렉션 API 확인')
  const r = await page.request.post(`http://127.0.0.1:8000/collections/${col.id}/reindex`,
    { data: { chunk_size: 250 } })
  ok(r.ok(), `② 재인덱싱 트리거 (HTTP ${r.status()})`)
  // 우하단 알림 대기
  await page.getByText('재인덱싱 완료', { exact: false }).first().waitFor({ timeout: 30000 })
  ok(true, '③ "재인덱싱 완료" 알림 표시')
  await page.screenshot({ path: `${OUT}/v436-notify.png` })
  console.log(fails.length ? `\nFAIL ${fails.length}` : '\nVERIFY436_UI_OK')
  process.exitCode = fails.length ? 1 : 0
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: `${OUT}/v436-debug.png` }).catch(() => {})
  process.exitCode = 1
} finally { await browser.close() }
