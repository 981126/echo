// R-244 数据看板「作品分析」区：总览 / 评论热词 / 评论管理（只读）3 个 tab。
// v13：流量分析、观众分析 tab 移除，指标并入总览右侧；悬浮指标切换左侧趋势曲线。
import { useState, type ReactNode } from 'react'
import {
  BarChart3,
  CircleAlert,
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Empty, Panel, StatTile, Thumb, TrendLine } from './charts'
import {
  formatDateTime,
  formatMonthDay,
  formatMonthDayTime,
  formatPercent,
  formatUnitValue,
  statusTone
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

function OverviewTab({ detail }: { detail: PostDetail }) {
  const { overview, fans, diagnosis } = detail
  const [metricKey, setMetricKey] = useState('plays')
  const [mode, setMode] = useState<'total' | 'added'>('total')
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
  // 播放量与涨粉量等累计指标的按天趋势已合并到同一张图（metric_trends），可切累计/新增
  const rawPoints = detail.metric_trends[metricKey] ?? []
  const points = rawPoints.map((point, index) => {
    const label = formatMonthDay(point.date)
    if (spec.kind !== 'count' || mode === 'total') return { label, value: point.value }
    const previous = index > 0 ? rawPoints[index - 1].value : null
    return { label, value: previous === null ? null : Math.max(0, point.value - previous) }
  })
  const available = points.filter((point) => point.value !== null).length >= 2
  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Panel
          title={`${spec.label}趋势`}
          hint="逐日数据；逐小时趋势 TikHub 未提供。悬浮右侧指标可切换曲线"
          extra={
            spec.kind === 'count' ? (
              <Tabs value={mode} onValueChange={(value) => setMode(value as 'total' | 'added')}>
                <TabsList className="h-8">
                  <TabsTrigger value="total" className="h-6 px-2.5 text-xs">累计</TabsTrigger>
                  <TabsTrigger value="added" className="h-6 px-2.5 text-xs">新增</TabsTrigger>
                </TabsList>
              </Tabs>
            ) : null
          }
        >
          {available ? (
            <TrendLine
              points={points}
              ariaLabel={`${spec.label}趋势`}
              axisFormat={
                spec.unit === 'ratio'
                  ? (value) => `${(value * 100).toFixed(0)}%`
                  : spec.unit === '秒'
                    ? (value) => `${value.toFixed(0)}s`
                    : undefined
              }
            />
          ) : (
            <Empty text="该指标暂无足够趋势数据（需要至少 2 天同步快照）" />
          )}
        </Panel>

        <Panel title="数据" hint="流量 / 观看质量 / 观众数据合并；悬浮指标切换左侧曲线">
          <div className="grid grid-cols-2 gap-x-2 gap-y-1.5">
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

      <Panel title="作品诊断" hint="只对比本账号近 30 条相近作品在相同发布天数的播放中位数，不做因果推断">
        <p className="text-sm font-medium">{diagnosis.conclusion || '暂无数据'}</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{diagnosis.detail || '暂无可比较的历史作品。'}</p>
        <div className="mt-3 grid grid-cols-2 gap-2.5">
          <StatTile label="平均播放占比" value={formatPercent(diagnosis.avg_view_proportion)} />
          <StatTile label="收藏率" value={formatPercent(diagnosis.favorite_rate)} />
        </div>
        {diagnosis.note ? <p className="mt-2 text-[11px] leading-4 text-muted-foreground">{diagnosis.note}</p> : null}
      </Panel>
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
  return (
    <div className="space-y-3">
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
          <p className="text-[11px] text-muted-foreground">已同步 {comments.total} 条公开评论（按点赞排序，最多 50 条；同步时间为本地保存时间）</p>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {comments.items.map((comment) => (
              <li key={comment.id} className="flex flex-col gap-1 px-3 py-2.5 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-xs font-medium">{comment.user || '抖音用户'}</span>
                    <span className="text-[10px] text-muted-foreground">同步于 {formatDateTime(comment.synced_at)}</span>
                  </div>
                  <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">{comment.text}</p>
                </div>
                <span className="tnum mt-1 flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground sm:mt-0">
                  <ThumbsUp className="h-3 w-3" />
                  {comment.likes}
                </span>
              </li>
            ))}
          </ul>
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

export function PostAnalysis({ detail, refreshing, refreshError, onRefresh, onRefreshComments, onOpenVideoReview }: PostAnalysisProps) {
  const { post } = detail
  return (
    <section className="rounded-xl border border-border bg-card shadow-[var(--shadow-card)]">
      <header className="flex flex-col gap-3 border-b border-border p-4 md:flex-row md:items-start md:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <Thumb url={post.cover_url} alt={post.title || '作品封面'} className="h-[72px] w-[54px] shrink-0 rounded-md border border-border" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="line-clamp-2 min-w-0 text-sm font-semibold leading-5" title={post.title}>{post.title || '无标题作品'}</h2>
              <Badge variant={statusTone(post.status)} className="shrink-0">{post.status_label || '—'}</Badge>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              发布于 {formatMonthDayTime(post.publish_time)}
              {post.duration_seconds ? ` · 时长 ${post.duration_seconds} 秒` : ''}
              {' · '}数据更新至 {formatDateTime(detail.data_time)}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={refreshing} onClick={onRefresh}>
            {refreshing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
            {refreshing ? '更新中…' : '更新数据'}
          </Button>
          <Button variant="outline" size="sm" onClick={onOpenVideoReview}>
            <BarChart3 className="mr-1.5 h-3.5 w-3.5" />
            去视频复盘
          </Button>
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
          数据已超过 6 小时未更新，{detail.private_available ? '正在自动获取最新数据…' : '可点「更新数据」获取最新数据'}
        </p>
      ) : null}

      <Tabs defaultValue="overview">
        <div className="overflow-x-auto px-4 pt-3">
          <TabsList className="w-max">
            <TabsTrigger value="overview">总览</TabsTrigger>
            <TabsTrigger value="words">评论热词</TabsTrigger>
            <TabsTrigger value="comments">评论管理</TabsTrigger>
          </TabsList>
        </div>
        <div className="p-4">
          <TabsContent value="overview"><OverviewTab detail={detail} /></TabsContent>
          <TabsContent value="words"><CommentWordsTab detail={detail} /></TabsContent>
          <TabsContent value="comments"><CommentsTab detail={detail} refreshing={refreshing} onRefresh={onRefreshComments} /></TabsContent>
        </div>
      </Tabs>
    </section>
  )
}
