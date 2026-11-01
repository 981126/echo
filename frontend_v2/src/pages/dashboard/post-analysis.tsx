// R-244 数据看板「作品分析」区：总览 / 评论热词 / 评论管理（只读）3 个 tab。
// v13：流量分析、观众分析 tab 移除，指标并入总览右侧；悬浮指标切换左侧趋势曲线。
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import {
  BarChart3,
  ChevronDown,
  CircleAlert,
  Mic,
  ExternalLink,
  Heart,
  Loader2,
  MessageCircle,
  MessageSquareText,
  Play,
  RefreshCw,
  Share2,
  ShieldAlert,
  Star,
  ThumbsUp
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CrossfadeTrendLine, Empty, Panel, Thumb } from './charts'
import {
  formatCount,
  formatDateTime,
  formatMonthDay,
  formatMonthDayTime,
  formatPercent,
  formatUnitValue,
} from './format'
import type { PostDetail } from './types'

const DOUYIN_COMMENT_ADMIN = 'https://creator.douyin.com/creator-micro/data/comment'

export interface PostAnalysisProps {
  detail: PostDetail
  refreshing: boolean
  /** 最近一次刷新失败原因（展示「刷新失败：原因」+ 重试，旧数据保留） */
  refreshError: string | null
  onRefresh: () => void
  /** 评论空状态里的「刷新评论」：走非强制刷新，遵守后端 6 小时缓存限制 */
  onRefreshComments: () => void
  onOpenVideoReview: () => void
  /** 在视频复盘页内嵌时隐藏「去视频复盘」按钮（v30：整个作品分析卡片搬到视频复盘复用） */
  showVideoReviewLink?: boolean
  /** v32：点击头部可下拉切换视频（视频复盘页使用），每项带封面/播放/点赞/收藏/分享 */
  videoOptions?: Array<{
    post_id: number
    title: string
    cover_url?: string | null
    plays?: number | null
    likes?: number | null
    favorites?: number | null
    shares?: number | null
    status_label?: string | null
  }>
  onSelectVideo?: (postId: number) => void
  /** 文案脚本为空时展示「ASR 转写」按钮 */
  onTranscribe?: () => void
  transcribing?: boolean
}

/** 逐日趋势卡：累计 / 新增切换（数据缺失时显示数据积累中，不补 0） */
type MetricSpec = {
  key: string
  label: string
  unit: string
  icon?: ReactNode
  /** count = 累计计数器（可切累计/新增）；rate = 比率；seconds = 秒 */
  kind: 'count' | 'rate' | 'seconds'
}

const METRIC_SPECS: MetricSpec[] = [
  { key: 'plays', label: '播放量', unit: '次', icon: <Play className="h-3 w-3" />, kind: 'count' },
  { key: 'likes', label: '点赞量', unit: '次', icon: <Heart className="h-3 w-3" />, kind: 'count' },
  { key: 'comments', label: '评论量', unit: '条', icon: <MessageCircle className="h-3 w-3" />, kind: 'count' },
  { key: 'shares', label: '分享量', unit: '次', icon: <Share2 className="h-3 w-3" />, kind: 'count' },
  { key: 'favorites', label: '收藏量', unit: '次', icon: <Star className="h-3 w-3" />, kind: 'count' },
  { key: 'danmaku', label: '弹幕量', unit: '条', icon: <MessageSquareText className="h-3 w-3" />, kind: 'count' },
  { key: 'finish_rate', label: '完播率', unit: 'ratio', kind: 'rate' },
  { key: 'bounce_2s_rate', label: '2 秒跳出率', unit: 'ratio', kind: 'rate' },
  { key: 'finish_5s_rate', label: '5 秒完播率', unit: 'ratio', kind: 'rate' },
  { key: 'avg_play_seconds', label: '平均播放时长', unit: '秒', kind: 'seconds' },
  { key: 'avg_view_proportion', label: '平均播放占比', unit: 'ratio', kind: 'rate' },
  { key: 'follower_gain', label: '涨粉量', unit: '人', icon: <ThumbsUp className="h-3 w-3" />, kind: 'count' },
  { key: 'follower_rate', label: '涨粉率', unit: 'ratio', kind: 'rate' },
  { key: 'unfollowers', label: '脱粉量', unit: '人', kind: 'count' },
  { key: 'unfollower_rate', label: '脱粉率', unit: 'ratio', kind: 'rate' },
  { key: 'dislike_count', label: '不感兴趣量', unit: '人', kind: 'count' },
  { key: 'dislike_rate', label: '不感兴趣率', unit: 'ratio', kind: 'rate' },
  { key: 'fan_view_proportion', label: '粉丝播放占比', unit: 'ratio', kind: 'rate' }
]

function formatMetricValue(value: number | null | undefined, unit: string): string {
  if (unit === 'ratio') return formatPercent(value)
  return formatUnitValue(value, unit)
}

/** 右侧指标块：鼠标悬浮/键盘聚焦即切换左侧曲线（v13） */
function MetricTile({
  spec,
  value,
  active,
  onHover
}: {
  spec: MetricSpec
  value: number | null | undefined
  active: boolean
  onHover: () => void
}) {
  return (
    <button
      type="button"
      onMouseEnter={onHover}
      onFocus={onHover}
      aria-pressed={active}
      title={`悬浮查看「${spec.label}」趋势`}
      className={
        active
          ? 'rounded-lg bg-muted px-2 py-1.5 text-left transition-colors'
          : 'rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-muted/50'
      }
    >
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        {spec.icon}
        <span className="truncate">{spec.label}</span>
      </div>
      <div className="tnum mt-0.5 text-sm font-semibold leading-5">{formatMetricValue(value, spec.unit)}</div>
    </button>
  )
}

/** 本地日期（YYYY-MM-DD），用于按统计周期截取趋势点 */
function localDateString(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}


/** 从标题里解析 #话题 标签（抖音标题即描述，标签格式 #xxx） */
function extractTags(title: string): string[] {
  const matches = title.match(/#[^\s#]+/g) ?? []
  return Array.from(new Set(matches))
}

function ScriptTab({ detail, onTranscribe, transcribing }: { detail: PostDetail; onTranscribe?: () => void; transcribing?: boolean }) {
  const { transcript } = detail
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      {transcript.available ? (
        <>
          <p className="text-[11px] text-muted-foreground">
            ASR 转写文案（来自本地素材转写，可能有错别字；共 {transcript.text.length} 字）
          </p>
          <motion.div
            initial={{ opacity: 0.6 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3 }}
            className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border bg-muted/30 p-3 text-xs leading-6"
          >
            {transcript.text}
          </motion.div>
        </>
      ) : (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
          {transcript.has_video && onTranscribe ? (
            <motion.div initial={{ opacity: 0.7, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.25 }}>
              <Button size="sm" disabled={Boolean(transcribing)} onClick={onTranscribe}>
                {transcribing ? (
                  <>
                    <motion.span
                      className="mr-1.5 inline-block h-3.5 w-3.5 rounded-full border-2 border-current border-t-transparent"
                      animate={{ rotate: 360 }}
                      transition={{ repeat: Number.POSITIVE_INFINITY, duration: 0.9, ease: 'linear' }}
                    />
                    <motion.span animate={{ opacity: [0.5, 1, 0.5] }} transition={{ repeat: Number.POSITIVE_INFINITY, duration: 1.4 }}>
                      转写中…
                    </motion.span>
                  </>
                ) : (
                  <>
                    <Mic className="mr-1.5 h-3.5 w-3.5" />
                    ASR 转写
                  </>
                )}
              </Button>
            </motion.div>
          ) : null}
          <Empty
            text={
              transcript.has_video
                ? '暂无文案脚本：素材尚未完成 ASR 转写，点上方「ASR 转写」开始'
                : '暂无文案脚本：这条作品还没有关联本地素材，无法转写'
            }
          />
        </div>
      )}
    </div>
  )
}

/** 视频总览（数据看板作品详情用，也被视频复盘页复用）：左趋势曲线 + 右 18 项指标 */
export function VideoOverview({ detail }: { detail: PostDetail }) {
  const { overview, fans, diagnosis } = detail
  const [metricKey, setMetricKey] = useState('plays')
  // v22：视频总览的统计周期（近 3 / 7 / 14 日），只影响左侧曲线范围
  const [periodDays, setPeriodDays] = useState(7)
  const spec = METRIC_SPECS.find((item) => item.key === metricKey) ?? METRIC_SPECS[0]
  const audienceCards: Record<string, number | null> = Object.fromEntries(
    detail.audience.cards.map((card) => [card.key, card.value])
  )
  const values: Record<string, number | null | undefined> = {
    plays: overview.plays,
    likes: overview.likes,
    comments: overview.comments,
    shares: overview.shares,
    favorites: overview.favorites,
    danmaku: overview.danmaku,
    finish_rate: overview.finish_rate,
    bounce_2s_rate: overview.bounce_2s_rate,
    finish_5s_rate: overview.finish_5s_rate,
    avg_play_seconds: overview.avg_play_seconds,
    avg_view_proportion: overview.avg_view_proportion ?? diagnosis.avg_view_proportion,
    follower_gain: audienceCards.follower_gain ?? fans.follower_gain,
    follower_rate: audienceCards.follower_rate,
    unfollowers: audienceCards.unfollowers ?? fans.unfollowers,
    unfollower_rate: audienceCards.unfollower_rate,
    dislike_count: audienceCards.dislike_count,
    dislike_rate: audienceCards.dislike_rate,
    fan_view_proportion: fans.fan_view_proportion
  }
  // 播放量与涨粉量等指标趋势合并到同一张图（metric_trends），只展示指标本身的每日值（v16 去掉「新增」）
  const cutoff = new Date()
  cutoff.setDate(cutoff.getDate() - (periodDays - 1))
  const cutoffDate = localDateString(cutoff)
  const points = (detail.metric_trends[metricKey] ?? [])
    .filter((point) => point.date >= cutoffDate)
    .map((point) => ({ label: formatMonthDay(point.date), value: point.value }))
  return (
    <div className="grid gap-3 lg:grid-cols-10 lg:items-start">
      <div className="min-w-0 lg:col-span-6">
        <Panel
          title={`${spec.label}趋势`}
          extra={
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">统计周期</span>
              <Select value={String(periodDays)} onValueChange={(value) => setPeriodDays(Number(value))}>
                <SelectTrigger className="h-7 w-[92px] text-xs" aria-label="统计周期">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {([3, 7, 14] as const).map((days) => (
                    <SelectItem key={days} value={String(days)}>
                      近 {days} 日
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          }
        >
          <CrossfadeTrendLine
            transitionKey={`${metricKey}-${periodDays}`}
            points={points}
            ariaLabel={`${spec.label}趋势`}
            height={300}
            emptyText="该指标暂无足够趋势数据（需要至少 2 天同步快照）"
            axisFormat={
              spec.unit === 'ratio'
                ? (value) => `${(value * 100).toFixed(0)}%`
                : spec.unit === '秒'
                  ? (value) => `${value.toFixed(0)}s`
                  : undefined
            }
          />
        </Panel>
      </div>

      <div className="min-w-0 lg:col-span-4">
        <Panel title="数据" hint="流量 / 观看质量 / 观众数据合并；悬浮指标切换左侧曲线">
          <div className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
            {METRIC_SPECS.map((item) => (
              <MetricTile
                key={item.key}
                spec={item}
                value={values[item.key]}
                active={item.key === metricKey}
                onHover={() => setMetricKey(item.key)}
              />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  )
}

function CommentWordsTab({ detail }: { detail: PostDetail }) {
  const { comment_words: words } = detail
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-[11px] leading-5 text-muted-foreground">{words.note}</div>
      {words.items.length ? (
        <div className="columns-1 gap-x-8 md:columns-2">
          {words.items.map((item, index) => (
            <div key={`${item.word}-${index}`} className="mb-1 flex break-inside-avoid items-center gap-2 border-b border-border/60 py-1.5 text-xs last:border-0">
              <span className="tnum w-5 shrink-0 text-[10px] text-muted-foreground">{index + 1}</span>
              <span className="min-w-0 flex-1 truncate font-medium" title={item.word}>{item.word}</span>
              <span className="tnum shrink-0 text-[11px] text-muted-foreground">{item.count} 条评论</span>
            </div>
          ))}
        </div>
      ) : (
        <Empty text={words.total_comments < 3 ? '评论太少，暂无法统计热词' : '暂无热词数据'} />
      )}
    </div>
  )
}

function CommentsTab({ detail, refreshing, onRefresh }: { detail: PostDetail; refreshing: boolean; onRefresh: () => void }) {
  const { comments } = detail
  // v14：一页最多 10 条，滑动到底部自动加载下一页（数据一次取回最多 50 条，本地分页）
  const PAGE_SIZE = 10
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const viewportRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    setVisibleCount(PAGE_SIZE)
  }, [detail.post.post_id])
  // 滚动到底部才加载下一批（用监听 scroll 而不是 IntersectionObserver：内容短时避免自动一次性加载全部）
  useEffect(() => {
    const node = viewportRef.current
    if (!node || visibleCount >= comments.items.length) return
    const onScroll = () => {
      if (node.scrollTop + node.clientHeight >= node.scrollHeight - 24) {
        setVisibleCount((count) => Math.min(count + PAGE_SIZE, comments.items.length))
      }
    }
    node.addEventListener('scroll', onScroll, { passive: true })
    return () => node.removeEventListener('scroll', onScroll)
  }, [visibleCount, comments.items.length])
  const visibleComments = comments.items.slice(0, visibleCount)
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-[11px] leading-5 text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span className="flex items-start gap-1.5">
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          本页只读：回复 / 删除 / 举报请到抖音创作者中心操作（TikHub 只提供公开评论读取）
        </span>
        <Button variant="outline" size="sm" asChild>
          <a href={DOUYIN_COMMENT_ADMIN} target="_blank" rel="noreferrer">
            打开抖音评论管理
            <ExternalLink className="ml-1.5 h-3 w-3" />
          </a>
        </Button>
      </div>
      {comments.items.length ? (
        <>
          <p className="text-[11px] text-muted-foreground">
            已同步 {comments.total} 条公开评论（按点赞排序，最多 50 条；同步时间为本地保存时间）· 已展示 {visibleComments.length}/{comments.items.length} 条
          </p>
          <ScrollArea viewportRef={viewportRef} className="min-h-0 flex-1 rounded-lg border border-border">
            <ul className="divide-y divide-border">
              {visibleComments.map((comment) => (
                <li key={comment.id} className="flex flex-col gap-1 px-3 py-2.5 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-[11px] font-medium text-muted-foreground">{comment.user || '抖音用户'}</span>
                      <span className="text-[10px] text-muted-foreground/80">同步于 {formatDateTime(comment.synced_at)}</span>
                    </div>
                    <p className="mt-1 break-words text-xs leading-5 text-foreground">{comment.text}</p>
                  </div>
                  <span className="tnum mt-1 flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground sm:mt-0">
                    <ThumbsUp className="h-3 w-3" />
                    {comment.likes}
                  </span>
                </li>
              ))}
            </ul>
          </ScrollArea>
          <p className="text-center text-[11px] text-muted-foreground">
            {visibleCount < comments.items.length ? '向下滚动自动加载更多' : '已展示全部已同步评论'}
          </p>
        </>
      ) : (
        <Empty text="还没有同步到这条作品的评论">
          <Button variant="outline" size="sm" disabled={refreshing} onClick={onRefresh}>
            {refreshing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
            刷新评论
          </Button>
        </Empty>
      )}
    </div>
  )
}

export function PostAnalysis({ detail, refreshing, refreshError, onRefresh, onRefreshComments, onOpenVideoReview, showVideoReviewLink = true, videoOptions, onSelectVideo, onTranscribe, transcribing = false }: PostAnalysisProps) {
  const { post } = detail
  const postTags = post.tags?.length ? post.tags : extractTags(post.title || '')
  const [pickerOpen, setPickerOpen] = useState(false)
  const pickerRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (!pickerOpen) return
    const onPointerDown = (event: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(event.target as Node)) setPickerOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [pickerOpen])
  return (
    <section className="rounded-xl border border-border bg-card shadow-[var(--shadow-card)]">
      <header ref={pickerRef} className="relative flex flex-col gap-3 p-4 md:flex-row md:items-start md:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          {onSelectVideo ? (
            <button
              type="button"
              onClick={() => setPickerOpen((open) => !open)}
              aria-expanded={pickerOpen}
              aria-label="切换要查看的作品"
              className="flex min-w-0 cursor-pointer items-start gap-3 rounded-lg text-left transition-colors hover:bg-muted/40"
            >
              <Thumb url={post.cover_url} alt={post.title || '作品封面'} className="h-[72px] w-[54px] shrink-0 rounded-md border border-border" />
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-1.5">
                  <h2 className="min-w-0 truncate text-sm font-semibold leading-5" title={post.title}>{post.title || '无标题作品'}</h2>
                  <ChevronDown className={pickerOpen ? 'h-3.5 w-3.5 shrink-0 rotate-180 text-muted-foreground transition-transform' : 'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform'} />
                </div>
                {postTags.length ? (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {postTags.map((tag) => (
                      <span key={tag} className="rounded bg-muted px-1.5 py-0.5 text-[10px] leading-4 text-muted-foreground">{tag}</span>
                    ))}
                  </div>
                ) : null}
                <p className="mt-1 truncate text-[11px] text-muted-foreground">
                  发布于 {formatMonthDayTime(post.publish_time)}
                  {post.duration_seconds ? ` · 时长 ${post.duration_seconds} 秒` : ''}
                  {' · '}数据更新至 {formatDateTime(detail.data_time)}
                </p>
              </div>
            </button>
          ) : (
            <>
          <Thumb url={post.cover_url} alt={post.title || '作品封面'} className="h-[72px] w-[54px] shrink-0 rounded-md border border-border" />
          {/* v30：头像右侧分三段——标题 / 视频标签 / 发布时间·时长·更新时间（不再显示「通过」徽标） */}
          <div className="min-w-0 flex-1">
            <h2 className="min-w-0 truncate text-sm font-semibold leading-5" title={post.title}>{post.title || '无标题作品'}</h2>
            {postTags.length ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {postTags.map((tag) => (
                  <span key={tag} className="rounded bg-muted px-1.5 py-0.5 text-[10px] leading-4 text-muted-foreground">
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
            <p className="mt-1 truncate text-[11px] text-muted-foreground">
              发布于 {formatMonthDayTime(post.publish_time)}
              {post.duration_seconds ? ` · 时长 ${post.duration_seconds} 秒` : ''}
              {' · '}数据更新至 {formatDateTime(detail.data_time)}
            </p>
          </div>
            </>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={refreshing} onClick={onRefresh}>
            {refreshing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
            {refreshing ? '更新中…' : '更新数据'}
          </Button>
          {showVideoReviewLink ? (
            <Button variant="outline" size="sm" onClick={onOpenVideoReview}>
              <BarChart3 className="mr-1.5 h-3.5 w-3.5" />
              去视频复盘
            </Button>
          ) : null}
          {post.video_url ? (
            <Button variant="outline" size="sm" asChild>
              <a href={post.video_url} target="_blank" rel="noreferrer">
                <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                查看原视频
              </a>
            </Button>
          ) : (
            <Button variant="outline" size="sm" disabled title="平台未提供原视频链接">
              <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
              查看原视频
            </Button>
          )}
        </div>
        {onSelectVideo && videoOptions && pickerOpen ? (
          <div className="absolute left-4 right-4 top-full z-30 max-h-80 overflow-y-auto rounded-lg border border-border bg-card p-1 shadow-[var(--shadow-card)] md:left-4 md:right-4">
            {videoOptions.map((option) => (
              <button
                key={option.post_id}
                type="button"
                onClick={() => {
                  setPickerOpen(false)
                  onSelectVideo(option.post_id)
                }}
                className={
                  option.post_id === post.post_id
                    ? 'flex w-full cursor-pointer items-center gap-3 rounded-md bg-muted/60 px-2 py-2 text-left'
                    : 'flex w-full cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted/40'
                }
              >
                <Thumb url={option.cover_url ?? null} alt={option.title || '作品封面'} className="h-10 w-7 shrink-0 rounded border border-border" />
                <span className="min-w-0 flex-1">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="min-w-0 flex-1 truncate text-xs font-medium">{option.title || '无标题作品'}</span>
                    {option.status_label ? <span className="shrink-0 text-[10px] text-muted-foreground">{option.status_label}</span> : null}
                  </span>
                  <span className="tnum mt-0.5 flex flex-wrap gap-x-2.5 gap-y-0.5 text-[10px] text-muted-foreground">
                    <span>播放 {formatCount(option.plays)}</span>
                    <span>点赞 {formatCount(option.likes)}</span>
                    <span>收藏 {formatCount(option.favorites)}</span>
                    <span>分享 {formatCount(option.shares)}</span>
                  </span>
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </header>

      {detail.warnings.length ? (
        <div className="space-y-1.5 px-4 pt-3">
          {detail.warnings.map((warning) => (
            <p key={warning} className="flex items-start gap-1.5 rounded-lg border border-warning/40 bg-[rgba(245,158,11,0.08)] px-2.5 py-1.5 text-[11px] leading-4 text-warning">
              <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {warning}
            </p>
          ))}
        </div>
      ) : null}
      {refreshError ? (
        <div className="mx-4 mt-3 flex flex-col gap-2 rounded-lg border border-warning/40 bg-[rgba(245,158,11,0.08)] px-3 py-2 text-[11px] leading-5 text-warning sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-start gap-1.5">
            <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            刷新失败：{refreshError}（当前展示上一次成功的数据）
          </span>
          <Button variant="outline" size="sm" className="shrink-0" disabled={refreshing} onClick={onRefresh}>重试</Button>
        </div>
      ) : null}
      {detail.stale ? (
        <p className="px-4 pt-3 text-[11px] text-muted-foreground">
          数据已超过 6 小时未更新，可点「更新数据」获取最新数据
        </p>
      ) : null}

      <Tabs defaultValue="overview">
        <div className="flex items-center justify-between gap-3 px-4 pt-3">
          {!detail.transcript.available ? (
            <p className="order-2 flex shrink-0 items-center gap-1 text-[11px] text-warning">
              <CircleAlert className="h-3 w-3 shrink-0" />
              暂无文案，分析结果可能不准
            </p>
          ) : null}
          <div className="order-1 min-w-0 overflow-x-auto">
          <TabsList className="w-max">
            <TabsTrigger value="overview">视频总览</TabsTrigger>
            <TabsTrigger value="script">文案脚本</TabsTrigger>
            <TabsTrigger value="words">评论热词</TabsTrigger>
            <TabsTrigger value="comments">评论管理</TabsTrigger>
          </TabsList>
          </div>
        </div>
        <div className="p-4">
          {/* v21：三个 tab 内容区固定同高（约等于总览高度），切换不跳；内容超长内部滚动 */}
          <div className="h-[400px] overflow-y-auto pr-1">
            <TabsContent value="overview" className="h-[380px]"><VideoOverview detail={detail} /></TabsContent>
            <TabsContent value="script" className="h-[380px]"><ScriptTab detail={detail} onTranscribe={onTranscribe} transcribing={transcribing} /></TabsContent>
            <TabsContent value="words" className="h-[380px]"><CommentWordsTab detail={detail} /></TabsContent>
            <TabsContent value="comments" className="h-[380px]"><CommentsTab detail={detail} refreshing={refreshing} onRefresh={onRefreshComments} /></TabsContent>
          </div>
        </div>
      </Tabs>
    </section>
  )
}
