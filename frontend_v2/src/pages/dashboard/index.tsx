// R-244 数据看板首页：账号总览（数据中心）+ 近期作品 + 作品分析（点选后下方展开）。
// 数据获取：GET overview / works / works/{id}；刷新走后台任务，可用 useTaskScope 跨切页/刷新恢复。
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, useReducedMotion } from 'framer-motion'
import { BarChart3, CircleAlert, Info, Loader2, RefreshCw, Users } from 'lucide-react'
import { apiJson } from '@/api/client'
import { waitTaskResult } from '@/api/task'
import { useTaskScope } from '@/hooks/use-task-scope'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { toast } from '@/components/ui/toaster'
import { coverThumb } from '@/lib/covers'
import { EASE_OUT_EXPO, softIn } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { Empty, TrendLine } from './charts'
import {
  deltaToneClass,
  formatCount,
  formatDateTime,
  formatDelta,
  formatMonthDay,
  formatPercent,
  formatRankPercent,
  formatUnitValue
} from './format'
import { PostAnalysis } from './post-analysis'
import { WorksList } from './works-list'
import type {
  AccountAnalysis,
  AccountDiagnosis,
  DashboardOverview,
  DiagnosisKey,
  DiagnosisMetric,
  KpiCard as KpiCardData,
  PostDetail,
  RefreshResponse,
  WorkItem,
  WorksPage
} from './types'

// 与 hooks/use-task-scope.ts 的 sessionStorage 键保持一致：手动/自动刷新写的 task_id
// 由 useTaskScope 在切页或刷新浏览器后回扫恢复（其 run() 会吞掉提交失败，故这里自行提交以便 toast 错误）。
const OVERVIEW_SCOPE = 'douyin_dashboard_overview'
const AUTO_REFRESH_MS = 10 * 60 * 1000
const taskKey = (scope: string) => `echo.task.${scope}`
const autoKey = (name: string) => `echo.dashboard.auto.${name}`

/** 同一目标 10 分钟内只自动刷新一次（本会话） */
function allowAutoRefresh(name: string): boolean {
  const key = autoKey(name)
  const last = Number(sessionStorage.getItem(key) || 0)
  const now = Date.now()
  if (last && now - last < AUTO_REFRESH_MS) return false
  sessionStorage.setItem(key, String(now))
  return true
}

const DIAGNOSIS_ROWS: Array<{ key: DiagnosisKey; label: string; format: (value: number) => string }> = [
  { key: 'plays', label: '播放量', format: (value) => formatCount(value) },
  { key: 'finish_rate', label: '完播率', format: (value) => formatPercent(value) },
  { key: 'interact', label: '互动指数', format: (value) => value.toFixed(4) },
  { key: 'new_fans', label: '净增粉丝', format: (value) => formatCount(value) },
  { key: 'publish_count', label: '投稿数', format: (value) => `${value} 篇` }
]

function KpiCardView({ kpi }: { kpi: KpiCardData }) {
  const valueText = kpi.value === null ? '暂无数据' : formatCount(kpi.value)
  const missingNote = kpi.source === 'diagnosis' ? '账号诊断暂无数据，可点「更新数据」获取' : kpi.note || '数据积累中：需要至少 2 天相邻快照'
  const deltaText = kpi.delta !== null ? `较前 7 日 ${formatDelta(kpi.delta)}` : null
  const similarText =
    kpi.similar !== null && kpi.rank !== null ? `同类平均 ${formatCount(kpi.similar)} · 超过 ${formatRankPercent(kpi.rank)} 同类创作者` : null
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{kpi.label}</div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="tnum text-2xl font-semibold tracking-tight">{valueText}</span>
        {kpi.available ? (
          deltaText ? (
            <span className={cn('text-xs', deltaToneClass(kpi.delta))}>{deltaText}</span>
          ) : kpi.note ? (
            <span className="text-[11px] leading-4 text-muted-foreground">{kpi.note}</span>
          ) : null
        ) : (
          <span className="text-[11px] leading-4 text-muted-foreground">{missingNote}</span>
        )}
      </div>
      {kpi.available && similarText ? <div className="mt-1 text-[11px] text-muted-foreground">{similarText}</div> : null}
    </div>
  )
}

function DiagnosisCompare({ diagnosis }: { diagnosis: AccountDiagnosis | null }) {
  const available = Boolean(diagnosis?.available)
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">同类创作者对比</h3>
        {available && diagnosis?.similar_count ? (
          <span className="text-[11px] text-muted-foreground">同类创作者 {formatCount(diagnosis.similar_count)} 位</span>
        ) : null}
      </div>
      {available && diagnosis ? (
        <div className="mt-2">
          <div className="grid grid-cols-[56px_minmax(0,1fr)_minmax(0,1fr)_44px] items-center gap-1.5 border-b border-border pb-1.5 text-[10px] text-muted-foreground">
            <span>指标</span>
            <span>本账号</span>
            <span>同类平均</span>
            <span className="text-right">排名</span>
          </div>
          {DIAGNOSIS_ROWS.map((row) => {
            const metric: DiagnosisMetric | undefined = diagnosis[row.key]
            return (
              <div
                key={row.key}
                className="grid grid-cols-[56px_minmax(0,1fr)_minmax(0,1fr)_44px] items-center gap-1.5 border-b border-border/60 py-1.5 text-xs last:border-0"
              >
                <span className="truncate text-muted-foreground">{row.label}</span>
                <span className="tnum truncate font-medium">{metric?.own !== null && metric?.own !== undefined ? row.format(metric.own) : '—'}</span>
                <span className="tnum truncate text-muted-foreground">
                  {metric?.similar !== null && metric?.similar !== undefined ? row.format(metric.similar) : '—'}
                </span>
                <span className="tnum text-right text-muted-foreground">{formatRankPercent(metric?.rank)}</span>
              </div>
            )
          })}
        </div>
      ) : (
        <Empty className="mt-2" text="暂无数据：账号诊断尚未成功获取，可点右上角「更新数据」" />
      )}
    </div>
  )
}

function AverageMetrics({ analysis }: { analysis: AccountAnalysis | null }) {
  const available = Boolean(analysis?.available && analysis.items.length)
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">条均指标（近 7 日投稿）</h3>
        {available ? <span className="text-[11px] text-muted-foreground">数据更新至 {formatDateTime(analysis?.captured_at)}</span> : null}
      </div>
      {available && analysis ? (
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {analysis.items.map((item) => (
            <div key={item.key} className="rounded-lg border border-border px-2.5 py-2">
              <div className="truncate text-[11px] text-muted-foreground" title={item.label}>{item.label}</div>
              <div className="tnum mt-0.5 text-sm font-medium">{formatUnitValue(item.value, item.unit)}</div>
            </div>
          ))}
        </div>
      ) : (
        <Empty className="mt-2" text="暂无数据：投稿条均指标尚未成功获取，可点右上角「更新数据」" />
      )}
    </div>
  )
}

function AccountOverview({ data, busy, onRefresh }: { data: DashboardOverview; busy: boolean; onRefresh: () => void }) {
  const account = data.account
  const diagnosis = data.diagnosis
  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="space-y-4 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <h2 className="text-base font-semibold">数据中心</h2>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  aria-label="数据来源说明"
                  className="flex h-5 w-5 cursor-pointer items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <Info className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs text-pretty">
                数据来自 TikHub 抖音创作者接口；账号诊断统计近 7 日；本地趋势只覆盖近 120 天发布且已同步的作品，与抖音官方全账号口径可能不同。
              </TooltipContent>
            </Tooltip>
            <span className="text-xs text-muted-foreground">统计周期：{data.period?.label ?? '近 7 日'}</span>
          </div>
          <Button variant="outline" size="sm" disabled={busy} onClick={onRefresh}>
            {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
            {busy ? '更新中…' : '更新数据'}
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
          <span>
            数据更新至：<span className="text-foreground">{formatDateTime(diagnosis?.captured_at)}</span>
          </span>
          {account ? (
            <span className="flex min-w-0 items-center gap-1.5">
              <Avatar className="h-6 w-6">
                {account.avatar ? <AvatarImage src={coverThumb(account.avatar, 160)} alt={account.nickname} decoding="async" /> : null}
                <AvatarFallback>{account.nickname.slice(0, 1)}</AvatarFallback>
              </Avatar>
              <span className="max-w-[220px] truncate font-medium text-foreground">{account.nickname}</span>
              <Badge variant={data.private_available ? 'success' : 'secondary'} className="shrink-0">
                {data.private_available ? '创作者数据可用' : '仅公开数据'}
              </Badge>
            </span>
          ) : null}
        </div>

        <div>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">播放量趋势（近 7 日）</h3>
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent" />
              播放量
            </span>
          </div>
          {data.trend.available ? (
            <div className="mt-1.5">
              <TrendLine
                points={data.trend.points.map((point) => ({ label: formatMonthDay(point.date), value: point.value }))}
                ariaLabel="近 7 日每日播放量趋势"
                fillArea
              />
            </div>
          ) : (
            <Empty className="mt-2" text={data.trend.note || '数据积累中：需要至少 2 天同步数据'} />
          )}
          <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
            本地每日快照差值，仅统计近 120 天发布且已同步的 {data.trend.coverage.posts} 条作品；缺口日期表示当天算不出增量（不补 0）。
          </p>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-5 md:grid-cols-3">
          {data.kpis.map((kpi) => (
            <KpiCardView key={kpi.key} kpi={kpi} />
          ))}
        </div>
        <p className="text-[11px] leading-4 text-muted-foreground">
          播放量/净增粉丝取抖音账号诊断（与创作者中心口径一致）；主页访问量/作品点赞/作品分享/作品评论取本地每日快照差值，历史不足时显示「暂无对比」。
        </p>

        <div className="border-t border-border pt-4">
          <DiagnosisCompare diagnosis={diagnosis} />
        </div>

        <div className="border-t border-border pt-4">
          <AverageMetrics analysis={data.analysis} />
        </div>
      </div>
    </section>
  )
}

function WarningBars({ data, onGoCreators }: { data: DashboardOverview; onGoCreators: () => void }) {
  const blocked = data.credential?.status === 'invalid' || data.data_policy?.source === 'blocked'
  const policyReason = data.data_policy?.reason || ''
  const warnings = data.warnings.filter((warning) => !(blocked && warning === policyReason))
  return (
    <div className="space-y-2">
      {blocked ? (
        <div className="flex flex-col gap-2 rounded-lg border border-destructive/40 bg-[rgba(239,68,68,0.08)] px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-start gap-1.5 text-[11px] leading-5 text-destructive">
            <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>抖音创作者 Cookie 已失效（{policyReason || '接口拒绝访问'}），请重新保存；当前展示上次成功获取的数据。</span>
          </p>
          <Button variant="outline" size="sm" className="shrink-0" onClick={onGoCreators}>去博主管理</Button>
        </div>
      ) : !data.private_available ? (
        <div className="flex flex-col gap-2 rounded-lg border border-warning/40 bg-[rgba(245,158,11,0.08)] px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-start gap-1.5 text-[11px] leading-5 text-warning">
            <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>未启用创作者数据{policyReason ? `（${policyReason}）` : ''}，只能查看公开作品数据；观众画像 / 流量来源等私有指标不可用。</span>
          </p>
          <Button variant="outline" size="sm" className="shrink-0" onClick={onGoCreators}>去博主管理设置</Button>
        </div>
      ) : null}
      {warnings.map((warning) => (
        <p key={warning} className="flex items-start gap-1.5 rounded-lg border border-warning/40 bg-[rgba(245,158,11,0.08)] px-3 py-2 text-[11px] leading-5 text-warning">
          <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {warning}
        </p>
      ))}
    </div>
  )
}

function NoAccountState({ reason, onGoCreators }: { reason: string; onGoCreators: () => void }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-card px-6 py-16 text-center">
      <Users className="mx-auto h-8 w-8 text-muted-foreground" />
      <h2 className="mt-4 text-base font-semibold">还没有可用的抖音账号</h2>
      <p className="mt-2 text-sm text-muted-foreground">{reason || '请先创建并切换主博主，并绑定抖音账号'}</p>
      <p className="mt-1 text-xs text-muted-foreground">数据看板固定展示「当前主博主」绑定的抖音账号数据，不提供账号切换。</p>
      <Button className="mt-5" onClick={onGoCreators}>
        <Users className="mr-2 h-4 w-4" />
        去博主管理
      </Button>
    </div>
  )
}

function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-border bg-card px-6 py-16 text-center">
      <CircleAlert className="mx-auto h-8 w-8 text-muted-foreground" />
      <p className="mt-3 text-sm text-muted-foreground">数据加载失败：{message}</p>
      <Button variant="outline" className="mt-4" onClick={onRetry}>重试</Button>
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-3 rounded-xl border border-border bg-card p-4 lg:col-span-2">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-3.5 w-64" />
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-[88px]" />)}
        </div>
        <Skeleton className="h-40 w-full" />
      </div>
      <div className="space-y-2 rounded-xl border border-border bg-card p-4">
        <Skeleton className="h-5 w-28" />
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="flex gap-3 pt-2">
            <Skeleton className="h-[72px] w-[54px] shrink-0" />
            <div className="flex-1 space-y-2"><Skeleton className="h-3.5 w-4/5" /><Skeleton className="h-3 w-1/2" /></div>
          </div>
        ))}
      </div>
    </div>
  )
}

function AnalysisSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex gap-3">
        <Skeleton className="h-[72px] w-[54px] shrink-0" />
        <div className="flex-1 space-y-2 py-1"><Skeleton className="h-4 w-2/3" /><Skeleton className="h-3 w-1/2" /></div>
      </div>
      <Skeleton className="mt-4 h-9 w-72" />
      <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-20" />)}
      </div>
      <Skeleton className="mt-3 h-36 w-full" />
    </div>
  )
}

function AnalysisGuide() {
  return (
    <div className="rounded-xl border border-dashed border-border bg-card px-6 py-10 text-center">
      <BarChart3 className="mx-auto h-7 w-7 text-muted-foreground" />
      <p className="mt-3 text-sm text-muted-foreground">在右侧近期作品里点一条，查看这条作品的详细数据</p>
    </div>
  )
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const reduce = useReducedMotion()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [morePages, setMorePages] = useState<{ items: WorkItem[]; hasMore: boolean }>({ items: [], hasMore: false })
  const [loadingMore, setLoadingMore] = useState(false)
  const [overviewRunning, setOverviewRunning] = useState(false)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [postRunningId, setPostRunningId] = useState<number | null>(null)
  const [postError, setPostError] = useState<string | null>(null)
  const errorToasted = useRef(false)

  const overviewQ = useQuery({
    queryKey: ['dashboard', 'overview'],
    queryFn: () => apiJson<DashboardOverview>('/api/douyin-dashboard/overview'),
    refetchInterval: (query) => (query.state.data?.updating_task_id ? 2500 : false)
  })
  const worksQ = useQuery({
    queryKey: ['dashboard', 'works'],
    queryFn: () => apiJson<WorksPage>('/api/douyin-dashboard/works?limit=20&offset=0')
  })
  const detailQ = useQuery({
    queryKey: ['dashboard', 'post', selectedId],
    queryFn: () => apiJson<PostDetail>(`/api/douyin-dashboard/works/${selectedId}`),
    enabled: selectedId !== null,
    refetchInterval: (query) => (query.state.data?.updating_task_id ? 2500 : false)
  })

  // 跨切页/刷新恢复：任务 ID 已写进 sessionStorage，回到页面后 useTaskScope 回扫并回填结果
  const overviewScope = useTaskScope<{ ok?: boolean }>(OVERVIEW_SCOPE)
  const postScopeName = selectedId !== null ? `douyin_dashboard_post_${selectedId}` : 'douyin_dashboard_post_none'
  const postScope = useTaskScope<{ ok?: boolean }>(postScopeName)

  const invalidateOverview = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['dashboard', 'overview'] })
    void qc.invalidateQueries({ queryKey: ['dashboard', 'works'] })
  }, [qc])

  const invalidatePost = useCallback(
    (postId: number) => {
      void qc.invalidateQueries({ queryKey: ['dashboard', 'post', postId] })
      void qc.invalidateQueries({ queryKey: ['dashboard', 'works'] })
    },
    [qc]
  )

  const refreshOverview = useCallback(
    async (silent = false) => {
      const scopeKey = taskKey(OVERVIEW_SCOPE)
      setOverviewRunning(true)
      try {
        const response = await apiJson<RefreshResponse>('/api/douyin-dashboard/overview/refresh', { method: 'POST' })
        if (!response.task_id) throw new Error('未获取到更新任务编号')
        sessionStorage.setItem(scopeKey, String(response.task_id))
        await waitTaskResult(response.task_id)
        sessionStorage.removeItem(scopeKey)
        invalidateOverview()
        setOverviewError(null)
        if (!silent) toast.success('账号数据已更新')
      } catch (error) {
        sessionStorage.removeItem(scopeKey)
        const message = error instanceof Error ? error.message : '账号数据更新失败'
        setOverviewError(message)
        if (!silent) toast.error(message)
      } finally {
        setOverviewRunning(false)
      }
    },
    [invalidateOverview]
  )

  const refreshPost = useCallback(
    async (postId: number, force: boolean, silent = false) => {
      const scopeKey = taskKey(`douyin_dashboard_post_${postId}`)
      setPostRunningId(postId)
      try {
        const response = await apiJson<RefreshResponse>(`/api/douyin-dashboard/works/${postId}/refresh`, {
          method: 'POST',
          body: JSON.stringify({ force })
        })
        if (response.skipped) {
          setPostError(null)
          if (!silent) toast.info(response.reason || '数据已是最新')
          return
        }
        if (!response.task_id) throw new Error('未获取到更新任务编号')
        sessionStorage.setItem(scopeKey, String(response.task_id))
        await waitTaskResult(response.task_id)
        sessionStorage.removeItem(scopeKey)
        invalidatePost(postId)
        setPostError(null)
        if (!silent) toast.success('作品数据已更新')
      } catch (error) {
        sessionStorage.removeItem(scopeKey)
        const message = error instanceof Error ? error.message : '作品数据更新失败'
        setPostError(message)
        if (!silent) toast.error(message)
      } finally {
        setPostRunningId(null)
      }
    },
    [invalidatePost]
  )

  useEffect(() => {
    setPostError(null)
  }, [selectedId])

  // 恢复的场景：切页/刷新回来时任务已完成 → 结果已回填，重新拉一次页面数据
  useEffect(() => {
    if (!overviewScope.data) return
    sessionStorage.removeItem(taskKey(OVERVIEW_SCOPE))
    invalidateOverview()
  }, [overviewScope.data, invalidateOverview])

  useEffect(() => {
    if (!postScope.data || selectedId === null) return
    sessionStorage.removeItem(taskKey(`douyin_dashboard_post_${selectedId}`))
    invalidatePost(selectedId)
  }, [postScope.data, selectedId, invalidatePost])

  // 打开页面：账号诊断缺失/超 24h 时自动刷新一次（本会话 10 分钟内不重复）
  useEffect(() => {
    const data = overviewQ.data
    if (!data?.account || !data.private_available || !data.needs_refresh || data.updating_task_id) return
    if (overviewRunning || overviewScope.running) return
    if (!allowAutoRefresh('overview')) return
    void refreshOverview(true)
  }, [overviewQ.data, overviewRunning, overviewScope.running, refreshOverview])

  // 选中作品：详情缓存缺失/超 6h 时自动刷新一次（同一作品 10 分钟内不重复）
  useEffect(() => {
    const detail = detailQ.data
    if (!detail || selectedId === null || !detail.private_available || !detail.stale || detail.updating_task_id) return
    if (postRunningId === selectedId || postScope.running) return
    if (!allowAutoRefresh(`post-${selectedId}`)) return
    void refreshPost(selectedId, false, true)
  }, [detailQ.data, selectedId, postRunningId, postScope.running, refreshPost])

  // 首次加载失败：toast 一次（错误文案来自 apiJson 的 Error.message）
  useEffect(() => {
    if (!overviewQ.isError || errorToasted.current) return
    errorToasted.current = true
    toast.error(overviewQ.error instanceof Error ? overviewQ.error.message : '数据看板加载失败')
  }, [overviewQ.isError, overviewQ.error])

  useEffect(() => {
    if (!detailQ.isError || !detailQ.error) return
    toast.error(detailQ.error instanceof Error ? detailQ.error.message : '作品分析加载失败')
  }, [detailQ.isError, detailQ.error])

  // 刷新后回到第一页：清掉已加载的后续分页
  useEffect(() => {
    setMorePages({ items: [], hasMore: false })
  }, [worksQ.dataUpdatedAt])

  const works = [...(worksQ.data?.items ?? []), ...morePages.items]
  const hasMore = morePages.items.length ? morePages.hasMore : (worksQ.data?.has_more ?? false)
  const worksDataTime = works.reduce<string | null>((latest, item) => {
    if (!item.data_time) return latest
    return !latest || item.data_time > latest ? item.data_time : latest
  }, null)

  const overviewBusy = overviewRunning || overviewScope.running || Boolean(overviewQ.data?.updating_task_id)
  const detailBusy = selectedId !== null && (postRunningId === selectedId || postScope.running || Boolean(detailQ.data?.updating_task_id))

  async function loadMoreWorks() {
    if (loadingMore) return
    setLoadingMore(true)
    try {
      const page = await apiJson<WorksPage>(`/api/douyin-dashboard/works?limit=20&offset=${works.length}`)
      setMorePages((previous) => ({ items: [...previous.items, ...page.items], hasMore: page.has_more }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '加载更多作品失败')
    } finally {
      setLoadingMore(false)
    }
  }

  if (overviewQ.isPending) return <DashboardSkeleton />
  if (overviewQ.isError || !overviewQ.data) {
    return <LoadError message={overviewQ.error instanceof Error ? overviewQ.error.message : '未知错误'} onRetry={() => void overviewQ.refetch()} />
  }
  const data = overviewQ.data
  if (!data.account) return <NoAccountState reason={data.blocked_reason} onGoCreators={() => navigate('/creators')} />

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0.85, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={softIn}
      className="space-y-4 pb-10"
    >
      <WarningBars data={data} onGoCreators={() => navigate('/creators')} />
      {overviewError ? (
        <div className="flex flex-col gap-2 rounded-lg border border-warning/40 bg-[rgba(245,158,11,0.08)] px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-start gap-1.5 text-[11px] leading-5 text-warning">
            <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            刷新失败：{overviewError}（当前展示上一次成功的数据）
          </p>
          <Button variant="outline" size="sm" className="shrink-0" disabled={overviewBusy} onClick={() => void refreshOverview()}>重试</Button>
        </div>
      ) : null}

      <div className="grid min-w-0 gap-4 lg:grid-cols-3">
        <div className="min-w-0 lg:col-span-2">
          <AccountOverview data={data} busy={overviewBusy} onRefresh={() => void refreshOverview()} />
        </div>
        {/* 桌面端让近期作品卡与左侧卡片等高（absolute 填充行高，避免 20 条列表把右列撑高），列表内部滚动 */}
        <div className="relative min-w-0 lg:col-span-1">
          <div className="min-w-0 lg:absolute lg:inset-0">
            <WorksList
              items={works}
              total={worksQ.data?.total ?? 0}
              dataTime={worksDataTime}
              selectedId={selectedId}
              onSelect={setSelectedId}
              hasMore={hasMore}
              loading={worksQ.isPending}
              loadingMore={loadingMore}
              onLoadMore={() => void loadMoreWorks()}
              onRefresh={() => void refreshOverview()}
              refreshing={overviewBusy}
              error={worksQ.isError ? (worksQ.error instanceof Error ? worksQ.error.message : '未知错误') : null}
              onRetry={() => void worksQ.refetch()}
            />
          </div>
        </div>
      </div>

      {selectedId !== null ? (
        <motion.div
          initial={reduce ? false : { height: 0, opacity: 0.85 }}
          animate={{ height: 'auto', opacity: 1 }}
          transition={{ height: { duration: 0.26, ease: EASE_OUT_EXPO }, opacity: { duration: 0.22 } }}
          className="overflow-hidden"
        >
          <div className="pt-4">
            {detailQ.isError ? (
              <LoadError
                message={detailQ.error instanceof Error ? detailQ.error.message : '未知错误'}
                onRetry={() => void detailQ.refetch()}
              />
            ) : detailQ.data ? (
              <PostAnalysis
                detail={detailQ.data}
                refreshing={detailBusy}
                refreshError={postError}
                onRefresh={() => void refreshPost(selectedId, true)}
                onRefreshComments={() => void refreshPost(selectedId, false)}
                onOpenVideoReview={() => navigate(`/video-review?post=${selectedId}`)}
              />
            ) : (
              <AnalysisSkeleton />
            )}
          </div>
        </motion.div>
      ) : (
        <div className="pt-4">
          <AnalysisGuide />
        </div>
      )}
    </motion.div>
  )
}
