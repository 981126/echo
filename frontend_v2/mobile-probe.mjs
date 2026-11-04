/**
 * R-218 M220 移动端点检（只读）。
 *
 * 用法：cd frontend_v2 && node mobile-probe.mjs [--only=nav,pages,interact,motion] [--vp=320,390]
 * 前置：前端 http://127.0.0.1:3000、后端 :8000 运行；token 从仓库根 .env 的 ECHO_ACCESS_TOKEN 读取。
 *
 * 断言来源：requirements/R-218-mobile-adaptation.md §7 + development-design/R-218-mobile-adaptation.md §5.16
 * 三原则：流畅 / 原有动画保留 / 符合人的使用逻辑
 */
import { chromium } from 'playwright'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'

const ROOT = new URL('..', import.meta.url).pathname.replace(/\/$/, '')
const BASE = process.env.ECHO_WEB || 'http://127.0.0.1:3000'
const TOKEN = readFileSync(`${ROOT}/.env`, 'utf8').match(/^ECHO_ACCESS_TOKEN=(.*)$/m)[1].trim()
const OUT = `${ROOT}/.tmp/audit/mobile`
mkdirSync(`${OUT}/shots`, { recursive: true })

const arg = (name, dflt) => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`))
  return hit ? hit.split('=')[1] : dflt
}
const ONLY = arg('only', 'nav,pages,interact,anim,motion').split(',')
const VIEWPORTS = arg('vp', '320,375,390,412').split(',').map((w) => [Number(w), Math.round(Number(w) * 2.1)])

const ROUTES = [
  ['/home', '主页'],
  ['/dashboard', '数据看板'],
  ['/videos', '素材库'],
  ['/video-review', '视频复盘'],
  ['/drafts', '脚本工作台'],
  ['/inspiration', '灵感随手记'],
  ['/benchmark', '博主对标'],
  ['/creators', '博主管理'],
  ['/persona', '人设档案'],
  ['/prompts', 'AI 设置'],
  ['/chat', 'AI 对话']
]

const failures = []
const notes = []
const fail = (scope, msg) => { failures.push(`[${scope}] ${msg}`); console.log(`  ❌ [${scope}] ${msg}`) }
const pass = (scope, msg) => console.log(`  ✅ [${scope}] ${msg}`)
const note = (scope, msg) => { notes.push(`[${scope}] ${msg}`); console.log(`  ⚠️  [${scope}] ${msg}`) }

// 探针白名单（有明确原因；见设计 §5.16）。必须定义在 pageMetrics 内部（函数被注入浏览器上下文执行）
const pageMetrics = () => {
  const TOUCH_ALLOW = ['.ProseMirror button', '.script-editor-content button', '[role="checkbox"]', '[role="switch"]']
  const FONT_ALLOW = ['.ProseMirror', '.script-editor-content']
  const isAllowed = (el, selectors) => selectors.some((sel) => el.closest(sel))
  const vw = window.innerWidth
  const vis = (el) => {
    const cs = getComputedStyle(el)
    const r = el.getBoundingClientRect()
    return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0.01 && r.width > 0 && r.height > 0
  }
  const ownText = (el) => {
    let s = ''
    for (const n of el.childNodes) if (n.nodeType === 3) s += n.textContent
    return s.trim()
  }
  const inHScroll = (el) => {
    let p = el.parentElement
    while (p) {
      const ox = getComputedStyle(p).overflowX
      if (ox === 'auto' || ox === 'scroll') return true
      p = p.parentElement
    }
    return false
  }
  const main = document.querySelector('main')
  const offscreen = []
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el)) continue
    const r = el.getBoundingClientRect()
    if (r.right > vw + 2 || r.left < -2) {
      if (!inHScroll(el)) offscreen.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 50)} right=${Math.round(r.right)}`)
    }
  }
  const smallTouch = []
  for (const el of document.querySelectorAll('button, input, textarea, select, [role="button"], [role="tab"], [role="combobox"], [role="menuitem"], [role="option"]')) {
    if (!vis(el)) continue
    if (isAllowed(el, TOUCH_ALLOW)) continue
    if (el.tagName === 'INPUT' && ['checkbox', 'radio', 'file', 'range'].includes(el.getAttribute('type') || '')) continue
    const r = el.getBoundingClientRect()
    // 容差 0.5px：h-11=44px 在 flex/grid 拉伸下会出现 43.98 之类的亚像素
    if (r.width < 43.5 || r.height < 43.5) {
      smallTouch.push(`${el.tagName.toLowerCase()}[${(el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 16)}] ${Math.round(r.width)}x${Math.round(r.height)}`)
    }
  }
  const tinyFonts = []
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el) || el.children.length) continue
    if (isAllowed(el, FONT_ALLOW)) continue
    const t = ownText(el)
    if (!t) continue
    const fs = parseFloat(getComputedStyle(el).fontSize)
    if (fs < 12) tinyFonts.push(`${el.tagName.toLowerCase()}(${fs}px) "${t.slice(0, 16)}"`)
  }
  // R-218：switch/checkbox 视觉本体保持原尺寸，但所在行/包裹层热区必须 ≥44
  const smallSwitchRows = []
  for (const el of document.querySelectorAll('[role="switch"], [role="checkbox"]')) {
    if (!vis(el)) continue
    const host = el.closest('label') || el.parentElement
    if (!host) continue
    const r = host.getBoundingClientRect()
    if (r.width < 44 || r.height < 44) smallSwitchRows.push(`${el.getAttribute('role')} 行 ${Math.round(r.width)}x${Math.round(r.height)}`)
  }
  const tabBar = document.querySelector('nav[aria-label="底部导航"]')
  const tabInfo = (() => {
    if (!tabBar) return null
    const slots = [...tabBar.children[0].children]
    return {
      slots: slots.length,
      sizes: slots.map((s) => { const r = s.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)] }),
      active: slots.filter((s) => s.getAttribute('aria-current') === 'page').length,
      padBottom: getComputedStyle(tabBar).paddingBottom
    }
  })()
  return {
    vw,
    mainW: main ? main.clientWidth : null,
    mainSw: main ? main.scrollWidth : null,
    docW: document.documentElement.clientWidth,
    docSw: document.documentElement.scrollWidth,
    offscreen, smallTouch, tinyFonts, smallSwitchRows, tabBar: tabInfo
  }
}

const browser = await chromium.launch()
const consoleErrors = []

async function newMobileCtx(vp = [390, 844], extra = {}) {
  const ctx = await browser.newContext({ viewport: { width: vp[0], height: vp[1] }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, ...extra })
  await ctx.addInitScript((t) => localStorage.setItem('echo_v2_token', t), TOKEN)
  const page = await ctx.newPage()
  page.on('pageerror', (e) => consoleErrors.push(String(e).slice(0, 200)))
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
  return { ctx, page }
}

// ---------------------------------------------------------------- 1) 逐页静态指标
if (ONLY.includes('pages')) {
  console.log('\n===== [pages] 逐页无横溢 / 触控 ≥44 / 字号 ≥12 / 底部 Tab =====')
  for (const [w, h] of VIEWPORTS) {
    const { ctx, page } = await newMobileCtx([w, h])
    for (const [route, label] of ROUTES) {
      await page.goto(`${BASE}/#${route}`, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(1700)
      const m = await page.evaluate(pageMetrics)
      const tag = `${label}@${w}`
      if (m.mainSw > m.mainW + 1) fail(tag, `main 横向溢出 ${m.mainSw - m.mainW}px`)
      if (m.docSw > m.docW + 1) fail(tag, `文档横向溢出 ${m.docSw - m.docW}px`)
      if (m.offscreen.length) fail(tag, `${m.offscreen.length} 个元素越界且不可横滑：${m.offscreen.slice(0, 3).join(' | ')}`)
      if (m.smallTouch.length) fail(tag, `${m.smallTouch.length} 个触控目标 <44：${m.smallTouch.slice(0, 4).join(' | ')}`)
      if (m.tinyFonts.length) fail(tag, `${m.tinyFonts.length} 处字号 <12：${m.tinyFonts.slice(0, 4).join(' | ')}`)
      if (m.smallSwitchRows.length) fail(tag, `${m.smallSwitchRows.length} 个开关/复选行热区 <44：${m.smallSwitchRows.slice(0, 4).join(' | ')}`)
      if (!m.tabBar) fail(tag, '缺少底部 Tab 栏')
      else {
        if (m.tabBar.slots !== 6) fail(tag, `底部 Tab 槽位=${m.tabBar.slots}（期望 6）`)
        if (m.tabBar.sizes.some(([sw, sh]) => sw < 44 || sh < 44)) fail(tag, `底部 Tab 槽位尺寸不足：${JSON.stringify(m.tabBar.sizes)}`)
      }
      if (!failures.some((f) => f.startsWith(`[${tag}]`)) && !notes.some((n) => n.startsWith(`[${tag}]`))) pass(tag, 'ok')
      if (w === 390) await page.screenshot({ path: `${OUT}/shots/r218-390-${route.replace(/\W+/g, '')}.png` })
      if (w === 320) await page.screenshot({ path: `${OUT}/shots/r218-320-${route.replace(/\W+/g, '')}.png` })
    }
    await ctx.close()
  }

  // 登录页（无 token）
  for (const [w, h] of [[320, 568], [390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
    const page = await ctx.newPage()
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1000)
    const m = await page.evaluate(() => {
      const vw = innerWidth
      const bad = [...document.querySelectorAll('body *')].filter((el) => {
        const r = el.getBoundingClientRect()
        const cs = getComputedStyle(el)
        return cs.display !== 'none' && r.width > 0 && (r.right > vw + 2 || r.left < -2)
      })
      const small = [...document.querySelectorAll('button, input')].map((el) => el.getBoundingClientRect()).filter((r) => r.width > 0 && (r.width < 44 || r.height < 44))
      return { docSw: document.documentElement.scrollWidth, docW: document.documentElement.clientWidth, bad: bad.length, small: small.length }
    })
    const tag = `登录页@${w}`
    if (m.docSw > m.docW + 1) fail(tag, `文档横向溢出 ${m.docSw - m.docW}px`)
    if (m.small) fail(tag, `${m.small} 个触控目标 <44`)
    if (!failures.some((f) => f.startsWith(`[${tag}]`))) pass(tag, 'ok')
    await page.screenshot({ path: `${OUT}/shots/r218-login-${w}.png` })
    await ctx.close()
  }
}

// ---------------------------------------------------------------- 2) 导航/返回/滚动/弹层
if (ONLY.includes('nav')) {
  console.log('\n===== [nav] 底部 Tab / 更多 Sheet / 返回键关弹层 / 滚动现场 =====')
  const { ctx, page } = await newMobileCtx([390, 844])
  await page.goto(`${BASE}/#/videos`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1800)

  // 2.1 底部 Tab 切换 + 页面转场首帧（≥0.85）
  const tabSamples = await page.evaluate(async () => {
    const sample = []
    const wrap = () => document.querySelector('main > div')
    const t0 = performance.now()
    const tick = () => {
      const el = wrap()
      if (el) {
        const cs = getComputedStyle(el)
        sample.push({ t: performance.now() - t0, opacity: parseFloat(cs.opacity), transform: cs.transform })
      }
      if (performance.now() - t0 < 500) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
    return sample
  })
  const tab = page.locator('nav[aria-label="底部导航"] a[href="#/drafts"]')
  if (await tab.count()) {
    await tab.click()
    await page.waitForTimeout(600)
    const hash = await page.evaluate(() => location.hash)
    if (!hash.includes('/drafts')) fail('nav', `底部 Tab 未跳转（hash=${hash}）`)
    else pass('nav', '底部 Tab 可跳转')
    await page.goBack()
    await page.waitForTimeout(800)
    const backHash = await page.evaluate(() => location.hash)
    if (backHash.includes('/videos')) pass('nav', '返回键回到上一页')
    else fail('nav', `返回键未回上一页（hash=${backHash}）`)
  } else fail('nav', '找不到底部 Tab /drafts')

  // 2.3 转场首帧不再全透明 + 落定
  const pageT = await page.evaluate(async () => {
    const wrap = () => document.querySelector('main > div')
    const frames = []
    const t0 = performance.now()
    await new Promise((resolve) => {
      const tick = () => {
        const el = wrap()
        if (el) frames.push(parseFloat(getComputedStyle(el).opacity))
        if (performance.now() - t0 < 450) requestAnimationFrame(tick)
        else resolve(null)
      }
      requestAnimationFrame(tick)
    })
    const el = wrap()
    const cs = el ? getComputedStyle(el) : null
    return { frames, settled: cs ? { opacity: cs.opacity, transform: cs.transform, filter: cs.filter } : null }
  })
  // 采样开始于点击后，此时动画可能已过 1-2 帧；断言「存在中间帧且无 0」
  const live = pageT.frames.filter((x) => x > 0)
  if (live.some((x) => x < 0.999) && !live.some((x) => x <= 0.01)) pass('nav', `转场有中间帧且首帧不全透明（min=${Math.min(...live).toFixed(2)}）`)
  else if (!live.some((x) => x < 0.999)) note('nav', '转场采样未捕获中间帧（可能已完成），以 rAF 逐帧脚本结论为准')
  if (pageT.settled && pageT.settled.opacity === '1' && (pageT.settled.transform === 'none' || pageT.settled.transform === 'matrix(1, 0, 0, 1, 0, 0)') && pageT.settled.filter === 'none') pass('nav', '转场落定 opacity=1/transform none/filter none')
  else note('nav', `转场落定样式：${JSON.stringify(pageT.settled)}`)

  // 2.2 更多 Sheet：开、动画中间帧、4 项、≥44、返回键关闭且不改路由
  const moreBtn = page.locator('button[aria-label="更多"]')
  await moreBtn.click()
  await page.waitForTimeout(120)
  const midY = await page.evaluate(() => {
    const d = document.querySelector('[role="dialog"][aria-label="更多"]')
    if (!d) return null
    return Math.round(d.getBoundingClientRect().top)
  })
  await page.waitForTimeout(450)
  const sheet = await page.evaluate(() => {
    const d = document.querySelector('[role="dialog"][aria-label="更多"]')
    if (!d) return null
    const items = [...d.querySelectorAll('button')].map((b) => {
      const r = b.getBoundingClientRect()
      return { label: (b.textContent || '').trim().slice(0, 8), w: Math.round(r.width), h: Math.round(r.height) }
    })
    return { top: Math.round(d.getBoundingClientRect().top), items }
  })
  if (!sheet) fail('nav', '更多 Sheet 未打开')
  else {
    if (sheet.items.filter((i) => i.label).length === 4) pass('nav', '更多 Sheet 4 项')
    else fail('nav', `更多 Sheet 条目异常：${JSON.stringify(sheet.items)}`)
    if (sheet.items.some((i) => i.w < 44 || i.h < 44)) fail('nav', `更多 Sheet 条目 <44：${JSON.stringify(sheet.items)}`)
    if (midY !== null && sheet.top < midY + 5) note('nav', `Sheet 动画中间帧 top=${midY}→${sheet.top}（采样间隔偏大）`)
  }
  await page.screenshot({ path: `${OUT}/shots/r218-more-sheet.png` })
  // 返回键关闭 Sheet 且路由不变
  const before = await page.evaluate(() => location.hash)
  await page.goBack()
  await page.waitForTimeout(500)
  const afterClose = await page.evaluate(() => ({ hash: location.hash, open: !!document.querySelector('[role="dialog"][aria-label="更多"]') }))
  if (!afterClose.open && afterClose.hash === before) pass('nav', '返回键关闭更多 Sheet 且路由不变')
  else fail('nav', `返回键未关闭 Sheet：${JSON.stringify(afterClose)}`)

  // 2.4 滚动现场保持：videos 滚动 → 切 creators → 切回
  await page.goto(`${BASE}/#/videos`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1800)
  await page.evaluate(() => { const m = document.querySelector('main'); m.scrollTop = 700 })
  await page.waitForTimeout(200)
  await page.locator('nav[aria-label="底部导航"] a[href="#/creators"]').click().catch(() => {})
  await page.waitForTimeout(700)
  await page.goto(`${BASE}/#/videos`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1800)
  const restored = await page.evaluate(() => document.querySelector('main').scrollTop)
  if (restored > 650) pass('nav', `切页回来滚动位置恢复（${restored}px）`)
  else note('nav', `滚动恢复 ${restored}px（路由直接 goto 不经过 Tab，参考价值低）`)

  await ctx.close()
}

// ---------------------------------------------------------------- 3) 抽屉/弹窗全屏 + 开合动画 + 动画保留
if (ONLY.includes('interact')) {
  console.log('\n===== [interact] 抽屉/弹窗 <md 全屏、开合有中间帧、动画保留 =====')
  const { ctx, page } = await newMobileCtx([390, 844])
  await page.goto(`${BASE}/#/videos`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2000)

  // 打开素材编辑抽屉
  await page.locator('.line-clamp-2').first().click()
  await page.waitForTimeout(700)
  const drawer = await page.evaluate(() => {
    const d = [...document.querySelectorAll('[role="dialog"]')].pop()
    if (!d) return null
    const r = d.getBoundingClientRect()
    const btns = [...d.querySelectorAll('button')].filter((b) => { const br = b.getBoundingClientRect(); return br.width > 0 && br.bottom > innerHeight - 120 }).map((b) => (b.textContent || b.getAttribute('aria-label') || '').trim().slice(0, 8))
    return { w: Math.round(r.width), h: Math.round(r.height), vw: innerWidth, vh: innerHeight, footerBtns: btns }
  })
  if (!drawer) fail('interact', '素材编辑抽屉未打开')
  else {
    if (drawer.w === drawer.vw) pass('interact', `抽屉 <md 全屏（${drawer.w}/${drawer.vw}）`)
    else fail('interact', `抽屉非全屏 ${drawer.w}/${drawer.vw}`)
    if (drawer.footerBtns.length) pass('interact', `抽屉底部操作可见：${drawer.footerBtns.join(',')}`)
    else fail('interact', '抽屉底部操作不可见')
  }
  await page.screenshot({ path: `${OUT}/shots/r218-videos-drawer.png` })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)
  const drawerGone = await page.evaluate(() => document.querySelectorAll('[role="dialog"]').length)
  if (drawerGone === 0) pass('interact', '抽屉关闭后卸载无残留')
  else fail('interact', `抽屉关闭后仍挂载 ${drawerGone} 个 dialog`)

  // 播放弹窗
  await page.locator('[class*="aspect-[4/3]"]').first().click().catch(() => {})
  await page.waitForTimeout(700)
  const player = await page.evaluate(() => {
    const d = [...document.querySelectorAll('[role="dialog"]')].pop()
    return d ? { w: Math.round(d.getBoundingClientRect().width), vw: innerWidth } : null
  })
  if (player && player.w === player.vw) pass('interact', '播放弹窗 <md 全屏')
  else fail('interact', `播放弹窗宽度 ${player ? player.w : 'null'}/${player ? player.vw : '?'}`)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)

  // Tab 选中滑块动画（采集 pill 的 x 变化）
  await page.goto(`${BASE}/#/drafts`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1800)
  const pillMoves = await page.evaluate(async () => {
    const pill = document.querySelector('[role="tablist"] span[aria-hidden]')
    if (!pill) return null
    const xs = []
    const tab = [...document.querySelectorAll('[role="tab"]')][2]
    tab?.click()
    const t0 = performance.now()
    await new Promise((resolve) => {
      const tick = () => {
        const cur = document.querySelector('[role="tablist"] span[aria-hidden]')
        if (cur) xs.push(Math.round(cur.getBoundingClientRect().left))
        if (performance.now() - t0 < 400) requestAnimationFrame(tick)
        else resolve(null)
      }
      requestAnimationFrame(tick)
    })
    return xs
  })
  if (pillMoves && new Set(pillMoves).size >= 2) pass('interact', `Tab 选中滑块有中间帧（${pillMoves.length} 帧）`)
  else note('interact', 'Tab 滑块未捕获中间帧（可能已被 Radix 重挂载，用截图复核）')
  await page.screenshot({ path: `${OUT}/shots/r218-drafts-tabs.png` })
  await ctx.close()
}

// ---------------------------------------------------------------- 3b) 动画保留（作者硬要求：原有动画不得删/瞬切）
if (ONLY.includes('anim')) {
  console.log('\n===== [anim] 原有动画保留：逐帧采样必须出现中间帧 =====')
  const { ctx, page } = await newMobileCtx([390, 844])
  await page.goto(`${BASE}/#/home`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1800)

  // A) 页面转场：在页面内先启动 rAF 采样，再触发路由切换
  const pageTransition = await page.evaluate(async () => {
    const frames = []
    const t0 = performance.now()
    const link = document.querySelector('nav[aria-label="底部导航"] a[href="#/drafts"]')
    let clicked = false
    await new Promise((resolve) => {
      const tick = () => {
        if (!clicked && performance.now() - t0 > 30) {
          clicked = true
          link?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
        }
        const wrap = document.querySelector('main > div')
        if (wrap) frames.push(Number(getComputedStyle(wrap).opacity))
        if (performance.now() - t0 < 900) requestAnimationFrame(tick)
        else resolve(null)
      }
      requestAnimationFrame(tick)
    })
    const wrap = document.querySelector('main > div')
    const cs = wrap ? getComputedStyle(wrap) : null
    return { frames, settled: cs ? { o: cs.opacity, t: cs.transform, f: cs.filter } : null, hash: location.hash }
  })
  const mids = pageTransition.frames.filter((x) => x > 0.1 && x < 0.999)
  if (pageTransition.hash.includes('/drafts') && mids.length >= 2) pass('anim', `页面转场有 ${mids.length} 帧中间态（min=${Math.min(...mids).toFixed(2)}）`)
  else fail('anim', `页面转场动画缺失：hash=${pageTransition.hash} 中间帧=${JSON.stringify(pageTransition.frames.slice(0, 12))}`)
  if (pageTransition.settled && pageTransition.settled.o === '1' && pageTransition.settled.t === 'none' && pageTransition.settled.f === 'none') pass('anim', '转场落定 opacity=1 / transform none / filter none')
  else note('anim', `转场落定：${JSON.stringify(pageTransition.settled)}`)

  // B) 更多 Sheet 开合（面板 top 逐帧变化）
  const sheetAnim = await page.evaluate(async () => {
    const tops = []
    const btn = document.querySelector('button[aria-label="更多"]')
    let clicked = false
    const t0 = performance.now()
    await new Promise((resolve) => {
      const tick = () => {
        if (!clicked && performance.now() - t0 > 20) {
          clicked = true
          btn?.click()
        }
        const d = document.querySelector('[role="dialog"][aria-label="更多"]')
        if (d) tops.push(Math.round(d.getBoundingClientRect().top))
        if (performance.now() - t0 < 700) requestAnimationFrame(tick)
        else resolve(null)
      }
      requestAnimationFrame(tick)
    })
    return tops
  })
  if (new Set(sheetAnim).size >= 3) pass('anim', `更多 Sheet 开启动画有 ${new Set(sheetAnim).size} 种中间位置`)
  else fail('anim', `更多 Sheet 动画缺失：${JSON.stringify(sheetAnim.slice(0, 10))}`)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)

  // C) 素材库抽屉开合（面板 transform x 逐帧变化）
  await page.goto(`${BASE}/#/videos`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2000)
  const drawerAnim = await page.evaluate(async () => {
    const xs = []
    let clicked = false
    const t0 = performance.now()
    await new Promise((resolve) => {
      const tick = () => {
        if (!clicked && performance.now() - t0 > 20) {
          clicked = true
          document.querySelector('.line-clamp-2')?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
        }
        const d = [...document.querySelectorAll('[role="dialog"]')].pop()
        if (d) xs.push(Math.round(d.getBoundingClientRect().left))
        if (performance.now() - t0 < 800) requestAnimationFrame(tick)
        else resolve(null)
      }
      requestAnimationFrame(tick)
    })
    return xs
  })
  if (new Set(drawerAnim).size >= 3) pass('anim', `抽屉开启动画有 ${new Set(drawerAnim).size} 种中间位置`)
  else fail('anim', `抽屉开启动画缺失：${JSON.stringify(drawerAnim.slice(0, 10))}`)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)

  // D) Tab 选中滑块（pill left 逐帧变化）
  await page.goto(`${BASE}/#/drafts`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1800)
  const pillAnim = await page.evaluate(async () => {
    const xs = []
    const tabs = [...document.querySelectorAll('[role="tab"]')]
    let clicked = false
    const t0 = performance.now()
    await new Promise((resolve) => {
      const tick = () => {
        if (!clicked && performance.now() - t0 > 30 && tabs[2]) {
          clicked = true
          tabs[2].dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window, button: 0 }))
          tabs[2].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
        }
        const pill = document.querySelector('[role="tablist"] span[aria-hidden]')
        if (pill) xs.push(Math.round(pill.getBoundingClientRect().left))
        if (performance.now() - t0 < 600) requestAnimationFrame(tick)
        else resolve(null)
      }
      requestAnimationFrame(tick)
    })
    return xs
  })
  if (new Set(pillAnim).size >= 3) pass('anim', `Tab 选中滑块动画有 ${new Set(pillAnim).size} 种中间位置`)
  else note('anim', `Tab 滑块采样：${JSON.stringify(pillAnim.slice(0, 10))}`)

  // E) 流畅性：切页期间帧间隔
  await page.goto(`${BASE}/#/home`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const fps = await page.evaluate(async () => {
    const intervals = []
    const link = document.querySelector('nav[aria-label="底部导航"] a[href="#/videos"]')
    let clicked = false
    let last = performance.now()
    const t0 = last
    await new Promise((resolve) => {
      const tick = (now) => {
        intervals.push(now - last)
        last = now
        if (!clicked && now - t0 > 40) {
          clicked = true
          link?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
        }
        if (now - t0 < 1000) requestAnimationFrame(tick)
        else resolve(null)
      }
      requestAnimationFrame(tick)
    })
    const sorted = [...intervals].sort((a, b) => a - b)
    return { frames: intervals.length, p95: sorted[Math.floor(sorted.length * 0.95)], max: Math.max(...intervals) }
  })
  if (fps.p95 <= 34 && fps.max <= 100) pass('anim', `切页期间帧间隔 p95=${fps.p95.toFixed(1)}ms max=${fps.max.toFixed(1)}ms`)
  else note('anim', `切页期间帧间隔（无头环境参考）p95=${fps.p95.toFixed(1)}ms max=${fps.max.toFixed(1)}ms`)
  await ctx.close()
}

// ---------------------------------------------------------------- 4) 断点 / reduce / 流畅性
if (ONLY.includes('motion')) {
  console.log('\n===== [motion] 断点切换 / reduced-motion / 帧率 =====')
  const { ctx, page } = await newMobileCtx([390, 844])
  await page.goto(`${BASE}/#/home`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1800)
  const navState = async () => page.evaluate(() => ({
    vw: innerWidth,
    tab: !!document.querySelector('nav[aria-label="底部导航"]') && getComputedStyle(document.querySelector('nav[aria-label="底部导航"]')).display !== 'none',
    side: (() => { const a = document.querySelector('aside'); return a ? getComputedStyle(a).display !== 'none' : false })(),
    mainSw: document.querySelector('main').scrollWidth,
    mainW: document.querySelector('main').clientWidth,
    opacity: getComputedStyle(document.querySelector('main > div')).opacity
  }))
  const at390 = await navState()
  await page.setViewportSize({ width: 768, height: 900 })
  await page.waitForTimeout(300)
  const at768 = await navState()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(300)
  const back = await navState()
  if (at390.tab && !at390.side && at768.side && !at768.tab && back.tab) pass('motion', '断点 768 切换底部 Tab/侧栏互斥正常')
  else fail('motion', `断点导航异常：${JSON.stringify({ at390, at768, back })}`)
  if ([at390, at768, back].every((s) => s.mainSw <= s.mainW + 1)) pass('motion', '断点切换无横向溢出')
  else fail('motion', '断点切换出现横向溢出')
  await page.screenshot({ path: `${OUT}/shots/r218-bp-768.png` })
  await ctx.close()

  // reduce 上下文
  const reduce = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' })
  await reduce.addInitScript((t) => localStorage.setItem('echo_v2_token', t), TOKEN)
  const rp = await reduce.newPage()
  await rp.goto(`${BASE}/#/home`, { waitUntil: 'domcontentloaded' })
  await rp.waitForTimeout(1500)
  const reduceState = await rp.evaluate(async () => {
    const running = document.getAnimations().filter((a) => a.playState === 'running').map((a) => (a.animationName || a.constructor.name)?.toString().slice(0, 24))
    const mq = matchMedia('(prefers-reduced-motion: reduce)').matches
    const wrap = document.querySelector('main > div')
    const cs = wrap ? getComputedStyle(wrap) : null
    return { mq, running: running.slice(0, 10), runningCount: running.length, opacity: cs?.opacity, transform: cs?.transform }
  })
  if (reduceState.mq) {
    if (reduceState.runningCount === 0) pass('motion', 'reduce 下无运行中的 CSS 动画')
    else note('motion', `reduce 下仍有 CSS 动画：${JSON.stringify(reduceState.running)}`)
    if (reduceState.opacity === '1' && (reduceState.transform === 'none' || reduceState.transform === 'matrix(1, 0, 0, 1, 0, 0)')) pass('motion', 'reduce 下页面转场无位移/直接落定')
    else note('motion', `reduce 转场样式：${JSON.stringify({ o: reduceState.opacity, t: reduceState.transform })}`)
  } else fail('motion', 'reducedMotion 上下文未生效')
  await reduce.close()

  // 帧率采样（切页期间）
  const { ctx: fctx, page: fp } = await newMobileCtx([390, 844])
  await fp.goto(`${BASE}/#/home`, { waitUntil: 'domcontentloaded' })
  await fp.waitForTimeout(1800)
  const fps = await fp.evaluate(async () => {
    const intervals = []
    let last = performance.now()
    const start = last
    await new Promise((resolve) => {
      const tick = (now) => {
        intervals.push(now - last)
        last = now
        if (now - start < 800) requestAnimationFrame(tick)
        else resolve(null)
      }
      requestAnimationFrame(tick)
    })
    const sorted = [...intervals].sort((a, b) => a - b)
    return { frames: intervals.length, p95: sorted[Math.floor(sorted.length * 0.95)], max: Math.max(...intervals) }
  })
  if (fps.p95 <= 34 && fps.max <= 100) pass('motion', `帧率采样 p95=${fps.p95.toFixed(1)}ms max=${fps.max.toFixed(1)}ms`)
  else note('motion', `帧率采样（无头环境参考）p95=${fps.p95.toFixed(1)}ms max=${fps.max.toFixed(1)}ms`)
  await fctx.close()
}

await browser.close()

// 控制台错误
if (consoleErrors.length) fail('console', `${consoleErrors.length} 条 console.error/pageerror：${consoleErrors.slice(0, 4).join(' | ')}`)
else pass('console', '0 console.error/pageerror')

writeFileSync(`${OUT}/mobile-probe-result.json`, JSON.stringify({ failures, notes, consoleErrors }, null, 2))
console.log('\n================ 汇总 ================')
console.log(`失败 ${failures.length} 项 / 提示 ${notes.length} 项 / console 错误 ${consoleErrors.length} 条`)
if (failures.length) {
  console.log(failures.join('\n'))
  process.exit(1)
}
console.log('✅ R-218 移动端点检全部通过')
