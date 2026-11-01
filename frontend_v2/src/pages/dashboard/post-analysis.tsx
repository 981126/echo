// R-244 数据看板「作品分析」区：总览 / 流量分析 / 观众分析 / 评论热词 / 评论管理（只读）5 个 tab。
import { useState } from 'react'
import {
  BarChart3,
  CircleAlert,
  ExternalLink,
  Flame,
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
import { Bars, Donut, Empty, Panel, RatioRows, StatTile, Thumb, TrendLine, WatchTrend } from './charts'
import {
  formatDateTime,
  formatHeat,
  formatMonthDay,
  formatMonthDayTime,
  formatPercent,
  formatUnitValue,
  statusTone
} from './format'
import type { PostDetail, PostTrend } from './types'

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
function TrendCard({ title, hint, trend, ariaLabel }: { title: string; hint: string; trend: PostTrend; ariaLabel: string }) {
  const [mode, setMode] = useState<'total' | 'added'>('total')
  const points = trend.points.map((point) => ({
    label: formatMonthDay(point.date),
    value: mode === 'total' ? point.total : point.added
  }))
  return (
    <Panel
      title={title}
      hint={hint}
      extra={
        <Tabs value={mode} onValueChange={(value) => setMode(value as 'total' | 'added')}>
          <TabsList className="h-8">
            <TabsTrigger value="total" className="h-6 px-2.5 text-xs">累计</TabsTrigger>
            <TabsTrigger value="added" className="h-6 px-2.5 text-xs">新增</TabsTrigger>
          </TabsList>
        </Tabs>
      }
    >
      {trend.available ? <TrendLine points={points} ariaLabel={ariaLabel} /> : <Empty text={trend.note || '数据积累中：需要至少 2 天同步数据'} />}
      {trend.available && mode === 'added' ? (
        <p className="mt-1 text-[11px] text-muted-foreground">新增 = 相邻两日快照差值；首日没有前一天数据，显示为空缺（不补 0）。</p>
      ) : null}
    </Panel>
  )
}

function OverviewTab({ detail }: { detail: PostDetail }) {
  const { overview, fans, diagnosis } = detail
  const traffic = [
    { key: 'plays', label: '播放量', unit: '次', value: overview.plays, icon: <Play className="h-3 w-3" /> },
    { key: 'likes', label: '点赞量', unit: '次', value: overview.likes, icon: <Heart className="h-3 w-3" /> },
    { key: 'comments', label: '评论量', unit: '条', value: overview.comments, icon: <MessageCircle className="h-3 w-3" /> },
    { key: 'shares', label: '分享量', unit: '次', value: overview.shares, icon: <Share2 className="h-3 w-3" /> },
    { key: 'favorites', label: '收藏量', unit: '次', value: overview.favorites, icon: <Star className="h-3 w-3" /> },
    { key: 'danmaku', label: '弹幕量', unit: '条', value: overview.danmaku, icon: <MessageSquareText className="h-3 w-3" /> }
  ]
  return (
    <div className="space-y-3">
      <Panel title="流量数据" hint="该作品累计数据（0 为平台返回的真实 0）">
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {traffic.map((item) => (
            <StatTile key={item.key} label={item.label} icon={item.icon} value={formatUnitValue(item.value, item.unit)} />
          ))}
        </div>
      </Panel>

      <div className="grid gap-3 sm:grid-cols-2">
        <Panel title="完播率" hint="完整播放该视频的比例">
          <div className="tnum text-2xl font-semibold">{formatPercent(overview.finish_rate)}</div>
        </Panel>
        <Panel title="2 秒跳出率" hint="播放 2 秒内划走的比例（越低越好）">
          <div className="tnum text-2xl font-semibold">{formatPercent(overview.bounce_2s_rate)}</div>
        </Panel>
      </div>

      <TrendCard title="播放量趋势" hint="逐日数据；逐小时趋势 TikHub 未提供" trend={detail.play_trend} ariaLabel="作品播放量逐日趋势" />

      <Panel title="粉丝数据" hint="该作品带来的粉丝变化与粉丝播放占比">
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          <StatTile label="涨粉量" value={formatUnitValue(fans.follower_gain, '人')} icon={<ThumbsUp className="h-3 w-3" />} />
          <StatTile label="脱粉量" value={formatUnitValue(fans.unfollowers, '人')} />
          <StatTile label="粉丝播放占比" value={formatPercent(fans.fan_view_proportion)} />
        </div>
      </Panel>

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

function FlowTab({ detail }: { detail: PostDetail }) {
  const [watchKind, setWatchKind] = useState<'retention' | 'bounce'>('retention')
  const { overview, diagnosis, flow } = detail
  const series = watchKind === 'retention' ? flow.retention : flow.bounce
  const attractiveness: Array<{ key: string; label: string; value: string; hint?: string }> = [
    { key: 'finish', label: '完播率', value: formatPercent(overview.finish_rate) },
    { key: 'avg_second', label: '平均播放时长', value: formatUnitValue(overview.avg_play_seconds, '秒') },
    { key: 'bounce', label: '2s 跳出率', value: formatPercent(overview.bounce_2s_rate) },
    { key: 'finish_5s', label: '5s 完播率', value: formatPercent(overview.finish_5s_rate) },
    {
      key: 'avg_proportion',
      label: '平均播放占比',
      value: formatPercent(overview.avg_view_proportion ?? diagnosis.avg_view_proportion)
    }
  ]
  const sourceRows = flow.sources.map((source) => ({ label: source.name, ratio: source.ratio }))
  return (
    <div className="space-y-3">
      <Panel title="内容吸引力" hint="5 项观看质量指标；平台未返回的项明确标注暂无数据">
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {attractiveness.map((item) => (
            <StatTile key={item.key} label={item.label} value={item.value} hint={item.hint} />
          ))}
        </div>
      </Panel>

      <Panel
        title="观看趋势"
        hint="横轴为视频播放进度，纵轴为观众留存/跳出比例；实线为当前作品，虚线为同类作者参考"
        extra={
          <Tabs value={watchKind} onValueChange={(value) => setWatchKind(value as 'retention' | 'bounce')}>
            <TabsList className="h-8">
              <TabsTrigger value="retention" className="h-6 px-2.5 text-xs">留存分析</TabsTrigger>
              <TabsTrigger value="bounce" className="h-6 px-2.5 text-xs">跳出分析</TabsTrigger>
            </TabsList>
          </Tabs>
        }
      >
        {series.points.length ? (
          <>
            <WatchTrend points={series.points} ariaLabel={watchKind === 'retention' ? '留存分析趋势图' : '跳出分析趋势图'} />
            <p className="mt-1 text-[11px] text-muted-foreground">{series.reliable ? '该作品播放量充足，趋势可参考。' : '播放量较少，趋势仅供参考。'}</p>
          </>
        ) : (
          <Empty text="暂无数据：TikHub 未返回该作品的观看趋势" />
        )}
      </Panel>

      <Panel title="流量来源" hint="当前占比；TikHub 不提供与前 7 日的对比">
        {sourceRows.length ? <RatioRows items={sourceRows} ariaLabel="流量来源占比" /> : <Empty text="暂无数据：TikHub 未返回该作品的流量来源" />}
        {flow.unavailable.length ? (
          <ul className="mt-3 space-y-1.5 border-t border-border pt-3">
            {flow.unavailable.map((item) => (
              <li key={item} className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                <span>{item}</span>
                <span>暂无数据</span>
              </li>
            ))}
          </ul>
        ) : null}
      </Panel>
    </div>
  )
}

function AudienceTab({ detail }: { detail: PostDetail }) {
  const { audience } = detail
  const provinceRows = [
    ...audience.provinces.map((province) => ({ label: province.name, ratio: province.ratio })),
    ...(audience.province_rest > 0 ? [{ label: '其他', ratio: audience.province_rest, muted: true }] : [])
  ]
  return (
    <div className="space-y-3">
      <Panel title="观众数据" hint="该作品带来的关注 / 取关 / 不感兴趣数据">
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {audience.cards.map((card) => (
            <StatTile key={card.key} label={card.label} value={formatUnitValue(card.value, card.unit)} />
          ))}
        </div>
      </Panel>

      <TrendCard title="涨粉量趋势" hint="逐日数据；逐小时趋势 TikHub 未提供" trend={audience.fan_trend} ariaLabel="涨粉量逐日趋势" />

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="性别分布">
          {audience.gender.length ? <Donut items={audience.gender.map((item) => ({ label: item.label || item.key, ratio: item.ratio }))} ariaLabel="性别分布环形图" /> : <Empty />}
        </Panel>
        <Panel title="活跃分布" hint="未知 / 低活 / 轻度 / 中度 / 重度">
          {audience.active.length ? <Donut items={audience.active.map((item) => ({ label: item.label || item.key, ratio: item.ratio }))} ariaLabel="活跃分布环形图" /> : <Empty />}
        </Panel>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="年龄分布">
          {audience.age.length ? <Bars items={audience.age.map((item) => ({ label: item.label || item.key, ratio: item.ratio }))} ariaLabel="年龄分布柱状图" /> : <Empty />}
        </Panel>
        <Panel title="地域分布" hint="省份 Top 6，其余合计为「其他」；不画地图">
          {provinceRows.length ? <RatioRows items={provinceRows} ariaLabel="地域分布占比" /> : <Empty />}
          {audience.city_levels.length ? (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
              <span className="text-[11px] text-muted-foreground">城市等级：</span>
              {audience.city_levels.map((city) => (
                <Badge key={city.name} variant="secondary">
                  {city.name} {formatPercent(city.ratio)}
                </Badge>
              ))}
            </div>
          ) : null}
        </Panel>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="受众兴趣分布">
          {audience.interests.length ? <RatioRows items={audience.interests.map((item) => ({ label: item.name, ratio: item.ratio }))} ariaLabel="受众兴趣分布占比" /> : <Empty />}
        </Panel>
        <Panel title="受众关注热词" hint="近 7 日热度（TikHub 原始口径）">
          {audience.keywords.length ? (
            <ul className="space-y-1.5">
              {audience.keywords.map((keyword, index) => (
                <li key={keyword.word} className="flex items-center justify-between gap-2 rounded-lg border border-border px-2.5 py-1.5 text-xs">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="tnum w-4 shrink-0 text-[10px] text-muted-foreground">{index + 1}</span>
                    <span className="truncate" title={keyword.word}>{keyword.word}</span>
                  </span>
                  <span className="tnum flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
                    <Flame className="h-3 w-3 text-warning" />
                    {formatHeat(keyword.heat)}
                  </span>
                </li>
              ))}
            </ul>
          ) : <Empty />}
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
            <TabsTrigger value="flow">流量分析</TabsTrigger>
            <TabsTrigger value="audience">观众分析</TabsTrigger>
            <TabsTrigger value="words">评论热词</TabsTrigger>
            <TabsTrigger value="comments">评论管理</TabsTrigger>
          </TabsList>
        </div>
        <div className="p-4">
          <TabsContent value="overview"><OverviewTab detail={detail} /></TabsContent>
          <TabsContent value="flow"><FlowTab detail={detail} /></TabsContent>
          <TabsContent value="audience"><AudienceTab detail={detail} /></TabsContent>
          <TabsContent value="words"><CommentWordsTab detail={detail} /></TabsContent>
          <TabsContent value="comments"><CommentsTab detail={detail} refreshing={refreshing} onRefresh={onRefreshComments} /></TabsContent>
        </div>
      </Tabs>
    </section>
  )
}
