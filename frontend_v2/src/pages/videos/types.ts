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
  plays?: number | null
  plays_known?: boolean
  plays_source?: string
  likes?: number | null
  comments?: number | null
  favorites?: number | null
  shares?: number | null
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

/** R-179：`GET /api/library` 一页卡片（服务端已合并去重 + 筛选 + 游标分页） */
export interface LibraryPage {
  total: number
  filtered_total: number
  facets: { tags: string[] }
  items: CardItem[]
  next_cursor: string | null
  has_more: boolean
}

export const PAGE_SIZE = 20

/** 筛选条件 → `/api/library` 查询串（筛选/搜索/计数全部走服务端，前端不再内存过滤）。 */
export function buildLibraryQuery(f: Filters, cursor: string): string {
  const qs = new URLSearchParams()
  qs.set('limit', String(PAGE_SIZE))
  if (f.creatorId) qs.set('creator_id', String(f.creatorId))
  if (cursor) qs.set('cursor', cursor)
  for (const p of f.platforms) qs.append('platforms', p)
  for (const t of f.tags) qs.append('tags', t)
  if (f.status) qs.set('status', f.status)
  if (f.video) qs.set('video', f.video)
  if (f.ad) qs.set('ad', f.ad)
  if (f.kw.trim()) qs.set('kw', f.kw.trim())
  if (f.likesMin != null) qs.set('likes_min', String(f.likesMin))
  if (f.likesMax != null) qs.set('likes_max', String(f.likesMax))
  return qs.toString()
}

// R-243：封面缩略图工具移出到 lib/covers（全站共用），此处 re-export 保持既有 import/测试兼容。
export { coverThumb } from '@/lib/covers'
