// R-244 数据看板：后端 `/api/douyin-dashboard` 响应类型（对应开发设计 §7）。
// 后端 response_model=dict，字段以真实响应为准；前端类型手写维护，缺失字段一律 null 而非 0。

/** 账号总览：主博主绑定的抖音账号 */
export interface DashboardAccount {
  id: number
  nickname: string
  avatar: string | null
  /** 最近一次账号快照指标（v25/v26：粉丝/关注/获赞总量，显示在博主名称右侧） */
  followers: number | null
  following: number | null
  likes_total: number | null
}

/** 创作者 Cookie 摘要（只读，不含 Cookie 明文） */
export interface DashboardCredential {
  account_id: number
  enabled: boolean
  has_cookie: boolean
  /** valid / invalid / disabled / missing */
  status: string
  status_label: string
  last_validated_at: string | null
  last_success_at: string | null
  last_error: string
}

/** 数据源策略：source=creator 表示可拿创作者私有数据 */
export interface DashboardDataPolicy {
  source: string
  reason: string
  status: string
  enabled: boolean
  has_cookie: boolean
  status_label: string
}

/** 账号诊断单项：本账号值 / 同类创作者平均 / 排名分位（0~1） */
export interface DiagnosisMetric {
  own: number | null
  similar: number | null
  rank: number | null
}

export type DiagnosisKey = 'plays' | 'finish_rate' | 'interact' | 'new_fans' | 'publish_count'

/** 账号诊断（TikHub fetch_author_diagnosis，固定近 7 日；未成功时只有 available/captured_at） */
export interface AccountDiagnosis {
  available: boolean
  captured_at: string | null
  similar_count: number | null
  plays?: DiagnosisMetric
  finish_rate?: DiagnosisMetric
  interact?: DiagnosisMetric
  new_fans?: DiagnosisMetric
  publish_count?: DiagnosisMetric
}

/** 统计周期（作者 2026-11-01 要求：7/14/30/90 天可下拉） */
export type PeriodDays = 7 | 14 | 30 | 90

export interface PeriodInfo {
  start: string
  end: string
  days: number
  label: string
}

/** 账号总览指标卡（7 个指标，一行 4 个；点击切换下方趋势曲线） */
export interface KpiCard {
  key: string
  label: string
  unit: string
  /** 对应 series 的键（当前与 key 一致，保留字段便于以后扩展） */
  trend_key: string
  value: number | null
  prev: number | null
  delta: number | null
  /** diagnosis = 账号诊断口径（仅 7 日周期）；snapshot = 本地每日快照差值 */
  source: string
  similar: number | null
  rank: number | null
  available: boolean
  coverage: { posts: number; dates: string[] } | null
  note: string
}

/** 指标趋势曲线：mode=daily 表示「较上次同步增量」（断档时含间隔累计），cumulative 表示累计值（总粉丝量） */
export interface MetricSeries {
  key: string
  label: string
  unit: string
  mode: 'daily' | 'cumulative'
  /** value=null 表示当天无快照（图表断开，不补 0） */
  points: Array<{ date: string; value: number | null }>
}

export interface DashboardOverview {
  account: DashboardAccount | null
  credential: DashboardCredential | null
  data_policy: DashboardDataPolicy | null
  private_available: boolean
  /** 无主博主/无抖音账号时的整页空状态文案 */
  blocked_reason: string
  period: PeriodInfo | null
  diagnosis: AccountDiagnosis | null
  kpis: KpiCard[]
  /** key = plays/homepage_visits/likes/shares/comments/net_fans */
  series: Record<string, MetricSeries>
  needs_refresh: boolean
  stale: boolean
  updating_task_id: number | null
  warnings: string[]
}

/** 近期作品列表项 */
export interface WorkItem {
  post_id: number
  title: string
  cover_url: string | null
  publish_time: string | null
  /** approved / private / rejected / published / unknown */
  status: string
  status_label: string
  plays: number | null
  likes: number | null
  comments: number | null
  shares: number | null
  has_detail: boolean
  data_time: string | null
}

export interface WorksPage {
  items: WorkItem[]
  total: number
  has_more: boolean
}

/** 作品详情头部 */
export interface PostBrief {
  post_id: number
  title: string
  cover_url: string | null
  publish_time: string | null
  video_url: string | null
  duration_seconds: number | null
  status: string
  status_label: string
}

/** 作品累计流量（null = 平台未返回，不是 0） */
export interface PostOverview {
  plays: number | null
  likes: number | null
  comments: number | null
  shares: number | null
  favorites: number | null
  danmaku: number | null
  finish_rate: number | null
  finish_5s_rate: number | null
  bounce_2s_rate: number | null
  avg_play_seconds: number | null
  avg_view_proportion: number | null
}

/** 作品逐日趋势（累计 + 当日新增；新增首日为 null） */
export interface PostTrendPoint {
  date: string
  total: number
  added: number | null
}

export interface PostTrend {
  available: boolean
  mode: string[]
  points: PostTrendPoint[]
  note: string
}

export interface PostFans {
  follower_gain: number | null
  unfollowers: number | null
  fan_view_proportion: number | null
}

export interface PostDiagnosis {
  conclusion: string
  detail: string
  avg_view_proportion: number | null
  favorite_rate: number | null
  baseline_plays: number | null
  sample_count: number
  note: string
}

/** 观看趋势点：key=视频进度（如 00:00），current=当前作品，similar=同类作者参考 */
export interface WatchPoint {
  key: string
  current: number | null
  similar: number | null
}

export interface WatchSeries {
  points: WatchPoint[]
  reliable: boolean
}

export interface FlowSource {
  name: string
  ratio: number
}

export interface PostFlow {
  retention: WatchSeries
  bounce: WatchSeries
  sources: FlowSource[]
  /** TikHub 未提供的流量类型说明 */
  unavailable: string[]
}

/** 观众画像比率项（key 原始值，label 已映射中文） */
export interface RatioItem {
  key: string
  label: string
  ratio: number
}

export interface RegionItem {
  name: string
  ratio: number
}

export interface AudienceCard {
  key: string
  label: string
  value: number | null
  /** ratio = 比率；否则中文单位（人） */
  unit: string
}

export interface AudienceKeyword {
  word: string
  heat: number
}

export interface PostAudience {
  cards: AudienceCard[]
  fan_trend: PostTrend
  gender: RatioItem[]
  active: RatioItem[]
  age: Array<{ key: string; label: string; ratio: number }>
  provinces: RegionItem[]
  province_rest: number
  city_levels: RegionItem[]
  interests: RegionItem[]
  keywords: AudienceKeyword[]
}

export interface CommentWordItem {
  word: string
  count: number
  ratio: number
}

export interface CommentWords {
  items: CommentWordItem[]
  total_comments: number
  note: string
}

export interface CommentItem {
  id: number
  user: string
  text: string
  likes: number
  synced_at: string | null
}

export interface PostDetail {
  post: PostBrief
  data_time: string | null
  cached: boolean
  stale: boolean
  private_available: boolean
  overview: PostOverview
  play_trend: PostTrend
  /** v13：各指标按天趋势（总览左侧曲线悬浮切换用），key 见 METRIC_SPECS */
  metric_trends: Record<string, Array<{ date: string; value: number }>>
  fans: PostFans
  diagnosis: PostDiagnosis
  flow: PostFlow
  audience: PostAudience
  comment_words: CommentWords
  comments: { total: number; items: CommentItem[] }
  updating_task_id: number | null
  warnings: string[]
}

/** POST refresh 的两种返回：202 {task_id, reused} 或 200 {skipped, reason, data_time} */
export interface RefreshResponse {
  task_id?: number
  reused?: boolean
  skipped?: boolean
  reason?: string
  data_time?: string | null
}
