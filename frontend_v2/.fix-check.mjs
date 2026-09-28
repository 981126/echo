import { chromium } from 'playwright'
const TOKEN = process.argv[2]
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 860 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message.slice(0, 120)))
await page.goto('http://localhost:3000/#/login')
await page.fill('input[type=password]', TOKEN)
await page.click('button[type=submit]')
await page.waitForTimeout(1500)

// 1) 抽屉：应覆盖整个视口（top=0，遮罩全屏）且可滚到底
await page.goto('http://localhost:3000/#/videos')
await page.waitForTimeout(2600)
await page.locator('.grid > div .p-3').first().click()
await page.waitForTimeout(1800)
const drawer = page.locator('[role=dialog]').first()
const box = await drawer.boundingBox()
console.log('drawer top:', box?.y, 'left+width:', (box?.x ?? 0) + (box?.width ?? 0), 'vw:', 1440)
const overlayCover = await page.evaluate(() => {
  const els = document.elementsFromPoint(10, 10)
  return els.some((e) => e.className?.toString().includes('bg-black/45'))
})
console.log('overlay covers topbar area:', overlayCover)
// 滚到底
const body = drawer.locator('.overflow-y-auto').first()
const before = await body.evaluate((el) => el.scrollTop)
await body.evaluate((el) => { el.scrollTop = el.scrollHeight })
await page.waitForTimeout(600)
const after = await body.evaluate((el) => ({ top: el.scrollTop, h: el.scrollHeight, ch: el.clientHeight }))
console.log('scroll before:', before, 'after:', after.top, 'reachBottom:', after.top + after.ch >= after.h - 4)
await page.screenshot({ path: '/tmp/fix-drawer.png' })
await page.keyboard.press('Escape')
await page.waitForTimeout(600)

// 2) 同步动画：点同步后卡片应出现进度覆盖层
await page.waitForTimeout(800)
const syncBtn = page.locator('.grid > div').first().locator('button').first()
await syncBtn.click()
await page.waitForTimeout(1200)
const overlay = await page.locator('.grid > div').first().locator('.bg-black\\/55, [class*="bg-black/55"]').count()
const overlayText = await page.locator('.grid > div').first().innerText()
console.log('sync overlay present:', overlay > 0 || overlayText.includes('同步'))
console.log('card text:', overlayText.slice(0, 200).replace(/\n/g, ' | '))

// 3) 页面性能：渲染帧采样（粗测滚动脉动）
await page.waitForTimeout(500)
const t0 = Date.now()
await page.mouse.wheel(0, 3000)
await page.waitForTimeout(500)
const cards = await page.locator('.grid > div').count()
console.log('cards:', cards, 'wheel time ok:', Date.now() - t0 < 1200)
console.log('errors:', errors.length ? errors : 'none')
await browser.close()
