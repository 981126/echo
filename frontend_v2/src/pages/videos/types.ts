// 素材库卡片模型：本地素材 + 云端作品（works）合一
export interface VideoItem {
  id: number
  filename: string
  title: string
  creator_id?: number | null
  cover_url?: string | null
  platforms: string[]
  status: string
  planned_publish_at?: string | null
  published_at?: string | null
  is_ad: boolean
  ad_price?: number | null
  main_topics: string[]
  tags: string[]
  tags_confirmed: boolean
  created_at: string
  platform_post_id?: string | null
  work_id?: number | null
}

export interface LatestStat {
  likes?: number | null
  comments?: number | null
  collects?: number | null
}

export interface CloudPost {
  id: number
  platform: string
  platform_post_id?: string
  title?: string
  cover?: string
  publish_time?: string | null
  is_ad?: boolean
  ad_price?: number | null
  local_video_id?: number | null
  tags?: string[]
  latest_stat?: LatestStat | null
  url?: string
}

export interface WorkItem {
  id: number
  type: 'work' | 'post'
  title?: string
  cover?: string
  platforms?: string[]
  posts?: CloudPost[]
}

export interface CardItem {
  key: string
  kind: 'local' | 'cloud'
  id: number
  type?: 'work' | 'post'
  creator_id?: number | null
  title: string
  cover_url: string
  platforms: string[]
  tags: string[]
  status: string
  is_ad: boolean
  ad_price?: number | null
  merged: number
  cloudPosts: CloudPost[]
  local_video_id?: number | null
  hasVideo: boolean
  filename?: string
  tags_confirmed?: boolean
  date: string
}

export function hasRealFile(filename?: string | null): boolean {
  return !!filename && !filename.startsWith('__cloud__')
}

function cloudWorkToCard(w: WorkItem, videoById: Map<number, VideoItem>): CardItem {
  const posts = w.posts || []
  const anyLocal = posts.find((x) => x.local_video_id)
  const boundVideo = anyLocal?.local_video_id ? videoById.get(anyLocal.local_video_id) : undefined
  const tags: string[] = []
  posts.forEach((x) => (x.tags || []).forEach((t) => t && !tags.includes(t) && tags.push(t)))
  const prices = posts.filter((x) => x.ad_price != null).map((x) => Number(x.ad_price))
  if (boundVideo?.ad_price != null) prices.push(Number(boundVideo.ad_price))
  const first = posts[0]
  return {
    key: (w.type === 'work' ? 'w' : 'p') + w.id,
    kind: 'cloud',
    id: w.id,
    type: w.type,
    title: w.title || '（无标题）',
    cover_url: w.cover || '',
    tags,
    platforms: [...new Set(w.platforms || [])],
    status: 'published',
    is_ad: posts.some((x) => x.is_ad) || !!boundVideo?.is_ad,
    ad_price: prices.length ? Math.max(...prices) : null,
    merged: w.type === 'work' ? posts.length : 0,
    cloudPosts: posts,
    local_video_id: anyLocal?.local_video_id ?? null,
    hasVideo: hasRealFile(boundVideo?.filename),
    date: ((first?.publish_time || '') as string).slice(0, 10)
  }
}

export function buildCards(videos: VideoItem[], works: WorkItem[]): CardItem[] {
  const videoById = new Map(videos.map((v) => [v.id, v]))
  const linkedLocal = new Set<number>()
  ;(works || []).forEach((w) => (w.posts || []).forEach((p) => p.local_video_id && linkedLocal.add(p.local_video_id)))
  const local: CardItem[] = videos
    .filter((v) => !linkedLocal.has(v.id))
    .map((v) => ({
      key: 'v' + v.id,
      kind: 'local' as const,
      id: v.id,
      creator_id: v.creator_id,
      title: v.title || v.filename || '',
      cover_url: v.cover_url || '',
      platforms: [...new Set(v.platforms || [])],
      tags: [...new Set([...(v.main_topics || []), ...(v.tags || [])])],
      status: v.status,
      is_ad: v.is_ad,
      ad_price: v.ad_price == null ? null : Number(v.ad_price),
      merged: 0,
      cloudPosts: [],
      local_video_id: null,
      hasVideo: hasRealFile(v.filename),
      filename: v.filename,
      tags_confirmed: v.tags_confirmed,
      date: (v.published_at || v.planned_publish_at || v.created_at || '').slice(0, 10)
    }))
  const cloud = (works || []).map((w) => cloudWorkToCard(w, videoById))
  return [...local, ...cloud].sort((a, b) => (b.date < a.date ? -1 : 1))
}

export interface Filters {
  creatorId: number
  platforms: string[]
  status: string
  video: string
  ad: string
  kw: string
  tags: string[]
  likesMin: number | null
  likesMax: number | null
}

export const DEFAULT_FILTERS: Filters = {
  creatorId: 0,
  platforms: [],
  status: '',
  video: '',
  ad: '',
  kw: '',
  tags: [],
  likesMin: null,
  likesMax: null
}

const FILTERS_KEY = 'echo_v2:videos:filters.v1'

export function loadFilters(): Filters {
  try {
    const raw = localStorage.getItem(FILTERS_KEY)
    if (!raw) return DEFAULT_FILTERS
    return { ...DEFAULT_FILTERS, ...(JSON.parse(raw) || {}) }
  } catch {
    return DEFAULT_FILTERS
  }
}

export function saveFilters(f: Filters) {
  try {
    localStorage.setItem(FILTERS_KEY, JSON.stringify(f))
  } catch {
    /* ignore */
  }
}

export function applyFiltersTo(cards: CardItem[], a: Filters): CardItem[] {
  return cards.filter((c) => {
    if (a.kw && !(c.title || '').toLowerCase().includes(a.kw.toLowerCase())) return false
    if (a.status && c.status !== a.status) return false
    if (a.ad === 'ad' && !c.is_ad) return false
    if (a.ad === 'no' && c.is_ad) return false
    if (a.video === 'yes' && !c.hasVideo) return false
    if (a.video === 'no' && c.hasVideo) return false
    if (a.platforms.length && !a.platforms.some((x) => c.platforms.includes(x))) return false
    if (a.tags.length && !a.tags.every((x) => c.tags.includes(x))) return false
    if (a.likesMin != null || a.likesMax != null) {
      const likes = (c.cloudPosts || [])
        .map((x) => (x.latest_stat?.likes != null ? Number(x.latest_stat.likes) : null))
        .filter((v): v is number => v != null)
      const ok = likes.some((v) => (a.likesMin == null || v >= a.likesMin) && (a.likesMax == null || v <= a.likesMax))
      if (!ok) return false
    }
    return true
  })
}
