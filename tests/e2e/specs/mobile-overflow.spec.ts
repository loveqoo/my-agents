import { test, expect, devices, type Page } from '@playwright/test'

/* 모바일 회귀 — 아이폰 디스플레이 크기(SE 320 / 13 390 / 14 Pro Max 430)에서
   7개 뷰 전부 "페이지 레벨 가로 스크롤이 없는지" 가드한다(spec 022).
   끊김 없는 긴 콘텐츠가 레이아웃을 가로로 밀어내는 회귀를 잡는다.
   antd Tabs 등 내부에서 클리핑/스크롤되는 요소는 페이지를 밀지 않으므로 통과로 본다. */

const VIEWS: [string, RegExp][] = [
  ['개요', /개요/],
  ['에이전트', /에이전트/],
  ['빌딩 블록', /빌딩 블록/],
  ['모델', /^모델/],
  ['세션', /^세션/],
  ['승인', /승인/],
  ['Playground', /Playground/],
]

const PHONES: [string, (typeof devices)[string]][] = [
  ['iPhone SE', devices['iPhone SE']],
  ['iPhone 13', devices['iPhone 13']],
  ['iPhone 14 Pro Max', devices['iPhone 14 Pro Max']],
]

// 모바일은 사이더가 오버레이 → 햄버거로 연 뒤 메뉴 클릭. 숨은 중복 menuitem을 피해
// :visible로 스코프하고, antd 메뉴 트랜지션 중 actionability 차단은 force로 우회.
async function gotoView(page: Page, rx: RegExp) {
  const item = page.locator('[role="menuitem"]:visible').filter({ hasText: rx }).first()
  for (let attempt = 0; attempt < 4; attempt++) {
    if (!(await item.isVisible().catch(() => false))) {
      await page.locator('header button').first().click().catch(() => {})
      await page.waitForTimeout(450) // 슬라이드-인 애니메이션
    }
    try {
      await item.scrollIntoViewIfNeeded({ timeout: 1500 })
      await item.click({ timeout: 2500, force: true })
      return
    } catch {
      await page.waitForTimeout(300)
    }
  }
  throw new Error(`nav click failed: ${rx}`)
}

async function horizOverflow(page: Page) {
  return page.evaluate(() => {
    const de = document.documentElement
    const content = document.querySelector('.ant-layout-content')
    return {
      doc: de.scrollWidth - de.clientWidth,
      content: content ? content.scrollWidth - content.clientWidth : 0,
    }
  })
}

for (const [pname, device] of PHONES) {
  test.describe(`모바일 가로 오버플로 — ${pname}`, () => {
    // defaultBrowserType는 describe 그룹에서 설정 불가(워커 강제 분기) → 제외하고
    // 디바이스 메트릭(viewport/userAgent/isMobile/hasTouch 등)만 적용. 브라우저는
    // config의 mobile 프로젝트가 chromium으로 고정.
    const { defaultBrowserType: _ignored, ...metrics } = device
    test.use(metrics)

    test('7개 뷰 모두 페이지 가로 스크롤 없음', async ({ page }) => {
      test.setTimeout(90_000)
      await page.goto('/')
      // 모바일은 사이더가 접혀 로고가 안 보임 → 기본 뷰(에이전트) 헤더로 로드 대기.
      await expect(page.getByRole('heading', { name: '에이전트' }).first()).toBeVisible({ timeout: 20_000 })

      for (const [label, rx] of VIEWS) {
        await gotoView(page, rx)
        await page.waitForTimeout(500)
        const of = await horizOverflow(page)
        expect(of.doc, `${label}: documentElement 가로 오버플로 (${device.viewport?.width}px)`).toBeLessThanOrEqual(1)
        expect(of.content, `${label}: 콘텐츠 스크롤러 가로 오버플로 (${device.viewport?.width}px)`).toBeLessThanOrEqual(1)
      }
    })
  })
}
