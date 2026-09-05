// 时间线模型计算（R-061-C：自 HomeView 抽出的纯逻辑，UI 行为不变）
export const DAY = 86400000

const NAMES = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
const platformName = (p) => NAMES[p] || p || '综合'

function dayNum(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number)
  return Date.UTC(y, m - 1, d) / DAY
}

function fmtDate(d) {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`
}

function pickStep(spanDays) {
  if (spanDays <= 45) return 26
  if (spanDays <= 120) return 18
  if (spanDays <= 300) return 9
  return 5
}

export function buildTimelineModel(videos, cloudPosts) {
  const raw = []
  const todayS = fmtDate(new Date())
  for (const v of videos) {
    const date = v.published_at ? v.published_at.slice(0, 10) : v.planned_publish_at ? v.planned_publish_at.slice(0, 10) : ''
    if (!date || date > todayS) continue  // R-044：只显示今天及以前，未来计划不提前出现
    raw.push({
      id: v.id,
      key: 'v' + v.id,
      kind: 'video',
      date,
      status: v.published_at ? 'published' : 'planned',
      title: (v.title || (v.main_topics && v.main_topics[0]) || v.filename).slice(0, 14),
      fullTitle: v.title || v.filename,
      coverUrl: v.cover_url || '',
      srcLabel: ''
    })
  }
  for (const p of cloudPosts) {
    const date = p.publish_time ? p.publish_time.slice(0, 10) : ''
    if (!date || date > todayS) continue  // R-044：未来发布不显示
    raw.push({
      id: p.id,
      key: 'c' + p.id,
      kind: 'cloud',
      date,
      status: 'published',
      title: (p.title || '').slice(0, 14) || '云端作品',
      fullTitle: p.title || '云端作品',
      coverUrl: p.cover || '',
      srcLabel: p.creator_kind === 'benchmark' ? platformName(p.platform) + '·对标' : platformName(p.platform),
      local_video_id: p.local_video_id
    })
  }
  raw.sort((a, b) => (a.date > b.date ? -1 : 1))  // R-042：倒叙，最新在前（左）
  if (!raw.length) return { events: [], months: [], width: 0, todayLeft: null }

  const dates = raw.map(r => dayNum(r.date))
  const start = Math.min(...dates) - 3
  const end = Math.max(...dates, dayNum(fmtDate(new Date()))) + 6
  const span = Math.max(30, end - start)
  const step = pickStep(span)          // 基础步长：按整体跨度，空档不会被撑开
  const minSep = 94                   // 相邻作品最小像素间距（卡片不叠）

  // 严格按“最新→最旧”从左到右顺序排布：同一天多条按序排开，相邻不足最小间距只往右推
  let prev = -Infinity
  const events = raw.map((r) => {
    const base = (end - dayNum(r.date)) * step + step / 2
    const left = Math.max(base, prev + minSep)
    prev = left
    return { ...r, left }
  })

  // R-061：月份刻度“跟着事件走”——事件被推到哪，刻度就放到对应月份的最新事件旁，
  // 保证滑到最右（最早内容）也有日期刻度
  const months = []
  let lastYm = ''
  events.forEach((e) => {
    const ym = e.date.slice(0, 7)
    if (ym !== lastYm) {
      months.push({
        key: ym,
        label: `${ym.slice(0, 4)}年${Number(ym.slice(5, 7))}月`,
        left: Math.max(0, e.left - 46)
      })
      lastYm = ym
    }
  })

  const today = dayNum(fmtDate(new Date()))
  const todayLeft = today >= start && today <= end ? (end - today) * step + step / 2 : null
  const width = Math.max(span * step, (events.length ? Math.max(...events.map(e => e.left)) : 0) + 140)
  return { events, months, width, todayLeft }
}
