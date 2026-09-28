// 时间线模型：本地素材 + 云端作品 → 倒序横轴（最新在左）
export const DAY = 86400000

export interface VideoLike {
  id: number
  title?: string
  filename?: string
  main_topics?: string[]
  cover_url?: string
  published_at?: string | null
  planned_publish_at?: string | null
  platform_post_id?: string | null
  work_id?: number | null
}

export interface WorkLike {
  id: number
  title?: string
  cover?: string
  platform?: string
  srcLabel?: string
  creator_kind?: string
  publish_time?: string | null
  local_video_id?: number | null
}

export interface TlEvent {
  key: string
  kind: 'video' | 'cloud'
  id: number
  date: string
  status: 'published' | 'planned'
  title: string
  fullTitle: string
  coverUrl: string
  srcLabel: string
  left: number
}

export interface TlModel {
  events: TlEvent[]
  months: { key: string; label: string; left: number }[]
  width: number
  todayLeft: number | null
}

const NAMES: Record<string, string> = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
const platformName = (p?: string) => (p && NAMES[p]) || p || '综合'

function dayNum(dateStr: string) {
  const [y, m, d] = dateStr.split('-').map(Number)
  return Date.UTC(y, m - 1, d) / DAY
}

function fmtDate(d: Date) {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`
}

function pickStep(spanDays: number) {
  if (spanDays <= 45) return 26
  if (spanDays <= 120) return 18
  if (spanDays <= 300) return 9
  return 5
}

export function buildTimelineModel(videos: VideoLike[], cloudPosts: WorkLike[]): TlModel {
  const raw: Omit<TlEvent, 'left'>[] = []
  const todayS = fmtDate(new Date())
  for (const v of videos) {
    const date = v.published_at
      ? v.published_at.slice(0, 10)
      : v.planned_publish_at
        ? v.planned_publish_at.slice(0, 10)
        : ''
    if (!date || date > todayS) continue
    if (v.platform_post_id || v.work_id) continue
    raw.push({
      id: v.id,
      key: 'v' + v.id,
      kind: 'video',
      date,
      status: v.published_at ? 'published' : 'planned',
      title: (v.title || v.main_topics?.[0] || v.filename || '').slice(0, 14),
      fullTitle: v.title || v.filename || '',
      coverUrl: v.cover_url || '',
      srcLabel: ''
    })
  }
  for (const p of cloudPosts) {
    const date = p.publish_time ? p.publish_time.slice(0, 10) : ''
    if (!date || date > todayS) continue
    raw.push({
      id: p.id,
      key: 'c' + p.id,
      kind: 'cloud',
      date,
      status: 'published',
      title: (p.title || '').slice(0, 14) || '云端作品',
      fullTitle: p.title || '云端作品',
      coverUrl: p.cover || '',
      srcLabel: p.srcLabel || (p.creator_kind === 'benchmark' ? `${platformName(p.platform)}·对标` : platformName(p.platform))
    })
  }
  raw.sort((a, b) => (a.date > b.date ? -1 : 1))
  if (!raw.length) return { events: [], months: [], width: 0, todayLeft: null }

  const dates = raw.map((r) => dayNum(r.date))
  const start = Math.min(...dates) - 3
  const end = Math.max(...dates, dayNum(todayS)) + 6
  const span = Math.max(30, end - start)
  const step = pickStep(span)
  const minSep = 94

  let prev = -Infinity
  const events = raw.map((r) => {
    const base = (end - dayNum(r.date)) * step + step / 2
    const left = Math.max(base, prev + minSep)
    prev = left
    return { ...r, left }
  })

  const months: TlModel['months'] = []
  let lastYm = ''
  events.forEach((e) => {
    const ym = e.date.slice(0, 7)
    if (ym !== lastYm) {
      months.push({ key: ym, label: `${ym.slice(0, 4)}年${Number(ym.slice(5, 7))}月`, left: Math.max(0, e.left - 46) })
      lastYm = ym
    }
  })

  const today = dayNum(todayS)
  const todayLeft = today >= start && today <= end ? (end - today) * step + step / 2 : null
  const width = Math.max(span * step, (events.length ? Math.max(...events.map((e) => e.left)) : 0) + 140)
  return { events, months, width, todayLeft }
}
