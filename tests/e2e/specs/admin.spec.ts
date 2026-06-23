import { test, expect, type APIRequestContext } from '@playwright/test'

/* 어드민 UI(Chromium) — 실 백엔드(8000)에 연결된 상태로 주요 플로우 검증.
   생성한 데이터는 API로 정리해 시드 오염 방지. */

const API = process.env.API_BASE ?? 'http://127.0.0.1:8000'
const uniq = (p: string) => `${p}-${Date.now()}-${Math.floor(Math.random() * 1e4)}`

async function deleteAgentByName(request: APIRequestContext, name: string) {
  const agents = await (await request.get(`${API}/agents`)).json()
  const a = agents.find((x: { name: string; id: string }) => x.name === name)
  if (a) await request.delete(`${API}/agents/${a.id}`)
}

async function deletePersonaByName(request: APIRequestContext, name: string) {
  const list = await (await request.get(`${API}/personas`)).json()
  const p = list.find((x: { name: string; id: string }) => x.name === name)
  if (p) await request.delete(`${API}/personas/${p.id}`)
}

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('my-agents')).toBeVisible()
})

test('사이더 네비 — 6뷰 전환', async ({ page }) => {
  for (const label of ['개요', '에이전트', '빌딩 블록', '세션', '승인']) {
    await page.getByRole('menuitem', { name: new RegExp(label) }).click()
    await expect(page.getByRole('heading', { name: label }).first()).toBeVisible()
  }
})

test('개요 — 통계 타일 + 에이전트 수가 API와 일치', async ({ page, request }) => {
  await page.getByRole('menuitem', { name: '개요' }).click()
  await expect(page.getByText('에이전트', { exact: true }).first()).toBeVisible()
  const agents = await (await request.get(`${API}/agents`)).json()
  // 통계 타일에 에이전트 수가 노출되는지
  await expect(page.getByText(String(agents.length), { exact: true }).first()).toBeVisible()
})

test('에이전트 — 시드 목록 표시', async ({ page }) => {
  await page.getByRole('menuitem', { name: '에이전트' }).click()
  await expect(page.getByText('Research Assistant').first()).toBeVisible()
  await expect(page.getByText('Doc Translator').first()).toBeVisible()
})

test('에이전트 — UI에서 생성하면 목록에 등장 (생성 후 API로 정리)', async ({ page, request }) => {
  const name = uniq('e2e-agent')
  await page.getByRole('menuitem', { name: '에이전트' }).click()
  await page.getByRole('button', { name: '새 에이전트' }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByPlaceholder('예: 리서치 어시스턴트').fill(name)
  await dialog.getByRole('button', { name: '에이전트 생성' }).click()

  // 목록에 새 에이전트 등장 (실 DB 저장 → UI 갱신)
  await expect(page.getByText(name).first()).toBeVisible({ timeout: 15_000 })

  // 정리
  await deleteAgentByName(request, name)
})

test('에이전트 — 공개(A2A) 스위치 토글 (켜기 즉시, 끄기는 확인 모달)', async ({ page }) => {
  await page.getByRole('menuitem', { name: '에이전트' }).click()
  // 꺼져 있는 스위치의 '위치'를 찾아 고정 로케이터로 잡는다(상태 속성 셀렉터는
  // 토글되면 매칭에서 빠져 다른 요소로 재해석되므로 nth 사용).
  const switches = page.locator('button[role="switch"]')
  await expect(switches.first()).toBeVisible()
  const count = await switches.count()
  let idx = -1
  for (let i = 0; i < count; i++) {
    if ((await switches.nth(i).getAttribute('aria-checked')) === 'false') {
      idx = i
      break
    }
  }
  expect(idx, '꺼진 스위치 존재').toBeGreaterThanOrEqual(0)
  const off = switches.nth(idx)
  await off.click()
  await expect(off).toHaveAttribute('aria-checked', 'true', { timeout: 10_000 })
  // 다시 끄면 확인 모달 → "즉시 철회"로 비공개 처리
  await off.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: new RegExp('즉시 철회') }).click()
  await expect(off).toHaveAttribute('aria-checked', 'false', { timeout: 10_000 })
})

test('모델 — 뷰 렌더 + 시드 모델 표시', async ({ page }) => {
  await page.getByRole('menuitem', { name: '모델' }).click()
  await expect(page.getByRole('heading', { name: '모델' }).first()).toBeVisible()
  await expect(page.getByText('qwen3.6-35b').first()).toBeVisible()
  await expect(page.getByText('multilingual-e5-large').first()).toBeVisible()
})

test('빌딩 블록 — MCP 탭에 서버 표시', async ({ page }) => {
  await page.getByRole('menuitem', { name: '빌딩 블록' }).click()
  await page.getByRole('tab', { name: new RegExp('MCP') }).click()
  await expect(page.getByText('tavily').first()).toBeVisible()
})

test('빌딩 블록 — 페르소나 등록 → 편집 (014, 생성 후 API 정리)', async ({ page, request }) => {
  const name = uniq('e2e-persona')
  await page.getByRole('menuitem', { name: '빌딩 블록' }).click()
  // persona 탭이 기본 — "새 항목"으로 작성 폼 오픈
  await page.getByRole('button', { name: '새 항목' }).click()
  const create = page.getByRole('dialog')
  await expect(create.getByText('새 페르소나')).toBeVisible()
  await create.getByPlaceholder('예: 친절한 고양이').fill(name)
  // 톤 — 프리셋 선택(멀티) + 자유 입력 태그 추가
  const toneSelect = create.locator('.ant-select').first()
  await toneSelect.click()
  await page.getByTitle('친근함', { exact: true }).click()
  await page.getByTitle('격식체', { exact: true }).click()
  await toneSelect.locator('input').fill('자유톤')
  await toneSelect.locator('input').press('Enter')
  await create.getByPlaceholder(/너는 고양이다/).fill('너는 테스트 페르소나다.')
  await create.getByRole('button', { name: '등록' }).click()

  // 목록에 등장
  await expect(page.getByText(name).first()).toBeVisible({ timeout: 15_000 })

  // 톤이 쉼표 조인 문자열로 저장됐는지(API) — 프리셋 2종 + 자유 1종
  await expect(async () => {
    const list = await (await request.get(`${API}/personas`)).json()
    const p = list.find((x: { name: string; tone: string | null }) => x.name === name)
    expect(p?.tone).toBe('친근함, 격식체, 자유톤')
  }).toPass({ timeout: 10_000 })

  // 행 클릭 → 상세 → 편집 → 본문 변경 → 저장
  await page.getByText(name).first().click()
  await page.getByRole('button', { name: '편집' }).click()
  const edit = page.getByRole('dialog').filter({ hasText: '페르소나 편집' })
  await expect(edit).toBeVisible()
  await edit.getByPlaceholder(/너는 고양이다/).fill('수정된 본문이다.')
  await edit.getByRole('button', { name: '저장' }).click()

  // 저장 후 본문 반영 확인(API)
  await expect(async () => {
    const list = await (await request.get(`${API}/personas`)).json()
    const p = list.find((x: { name: string; body: string }) => x.name === name)
    expect(p?.body).toBe('수정된 본문이다.')
  }).toPass({ timeout: 10_000 })

  await deletePersonaByName(request, name)
})

test('세션 — 목록 렌더 + 행 클릭 시 상세', async ({ page }) => {
  await page.getByRole('menuitem', { name: '세션' }).click()
  const row = page.locator('tr', { hasText: 'sess-' }).first()
  await expect(row).toBeVisible()
  await row.click()
  // 상세 드로어(커스텀)에 에이전트/채널 등의 라벨이 보임
  await expect(page.getByText('채널').first()).toBeVisible()
})

test('Playground — 실 에이전트와 대화 + 인스펙터 트레이스', async ({ page }) => {
  test.setTimeout(150_000)
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  // 실 에이전트 로드 → Sender 입력창 노출
  const sender = page.getByPlaceholder(/메시지/)
  await expect(sender).toBeVisible({ timeout: 15_000 })
  await sender.fill('한 단어로 인사해줘')
  await sender.press('Enter')
  // 전체 응답 완료 시 trace 도착 → 인스펙터 자동 오픈 (실 LangGraph 경로 표시)
  await expect(page.getByText('턴 인스펙터')).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText('LangGraph 경로')).toBeVisible()
})

test('승인 — 카드 또는 빈 상태 렌더', async ({ page }) => {
  await page.getByRole('menuitem', { name: '승인' }).click()
  // 대기 건이 있으면 "승인 및 재개" 버튼, 없으면 빈 상태 문구
  const hasCard = await page.getByRole('button', { name: '승인 및 재개' }).first().isVisible().catch(() => false)
  const hasEmpty = await page.getByText('대기 중인 승인이 없습니다').isVisible().catch(() => false)
  expect(hasCard || hasEmpty).toBeTruthy()
})
