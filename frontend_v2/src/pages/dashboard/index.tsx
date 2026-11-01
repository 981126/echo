// R-244 数据看板首页：账号总览（数据中心）+ 近期作品 + 作品分析（点选后下方展开）。
// 数据获取：GET overview / works / works/{id}；刷新走后台任务，可用 useTaskScope 跨切页/刷新恢复。
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, useReducedMotion } from 'framer-motion'
import { BarChart3, CircleAlert, Info, Loader2, RefreshCw, Users } from 'lucide-react'
import { apiJson } from '@/api/client'
import { waitTaskResult } from '@/api/task'
import { useTaskScope } from '@/hooks/use-task-scope'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { toast } from '@/components/ui/toaster'
import { coverThumb } from '@/lib/covers'
import { EASE_OUT_EXPO, softIn } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { Empty, TrendLine } from './charts'
import { deltaToneClass, formatCount, formatDateTime, formatDelta, formatMonthDay } from './format'
import { PostAnalysis } from './post-analysis'
import { WorksList } from './works-list'
import type {
  DashboardOverview,
  KpiCard as KpiCardData,
  PeriodDays,
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

function KpiCardView({
  kpi,
  days,
  active,
  onSelect
}: {
  kpi: KpiCardData
  days: PeriodDays
  active: boolean
  onSelect: () => void
}) {
  const valueText = kpi.value === null ? '暂无数据' : formatCount(kpi.value)
  const deltaText = kpi.delta !== null ? formatDelta(kpi.delta) : null
  const hoverTimer = useRef<number | null>(null)
  // v7：鼠标悬浮即激活该指标（80ms 防抖，避免快速划过时曲线反复重绘）；点击同样生效
  const activate = () => onSelect()
  const onEnter = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current)
    hoverTimer.current = window.setTimeout(activate, 80)
  }
  const onLeave = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current)
    hoverTimer.current = null
  }
  useEffect(() => () => onLeave(), [])
  return (
    <button
      type="button"
      onClick={activate}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      onFocus={activate}
      aria-pressed={active}
      title={`悬浮/点击查看「${kpi.label}」在近 ${days} 日的趋势`}
      className={cn(
        'group relative flex h-full min-w-0 cursor-pointer flex-col rounded-lg px-3 py-2.5 text-left transition-colors',
        active ? 'bg-muted' : 'bg-transparent hover:bg-muted/40'
      )}
    >
      {/* 上：指标名 / 中：数字 / 下：较前 N 日对比（没有对比数据就留空，不显示提示文字） */}
      <div className={cn('text-[10px] text-muted-foreground', active && 'text-foreground')}>{kpi.label}</div>
      <div className="tnum mt-0.5 text-lg font-semibold leading-6 tracking-tight">{valueText}</div>
      <div
        className={cn('mt-0.5 min-h-3.5 text-[10px] leading-3.5', deltaText ? deltaToneClass(kpi.delta) : 'text-muted-foreground')}
        title={deltaText ? `较前 ${days} 日对比：${deltaText}` : undefined}
      >
        {deltaText}
      </div>
    </button>
  )
}

function AccountOverview({
  data,
  busy,
  onRefresh,
  periodDays,
  onPeriodChange,
  metricKey,
  onMetricChange
}: {
  data: DashboardOverview
  busy: boolean
  onRefresh: () => void
  periodDays: PeriodDays
  onPeriodChange: (days: PeriodDays) => void
  metricKey: string
  onMetricChange: (key: string) => void
}) {
  const reduce = useReducedMotion()
  const account = data.account
  const diagnosis = data.diagnosis
  const series = data.series[metricKey] ?? null
  const points = (series?.points ?? []).map((point) => ({ label: formatMonthDay(point.date), value: point.value }))
  const chartLabel = series ? `${series.label}${series.mode === 'daily' ? '（较上次同步增量）' : ''}` : '播放量'
  // v8：切换指标时保留旧曲线做交叉淡出（避免图表瞬间闪一下）
  const [fadeFrom, setFadeFrom] = useState<{ points: Array<{ label: string; value: number | null }>; label: string } | null>(null)
  useEffect(() => {
    if (!fadeFrom) return
    const timer = window.setTimeout(() => setFadeFrom(null), 280)
    return () => window.clearTimeout(timer)
  }, [fadeFrom])
  const switchMetric = (key: string) => {
    if (key === metricKey) return
    setFadeFrom({ points, label: chartLabel })
    onMetricChange(key)
  }
  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-[var(--shadow-card)]">
      <header className="flex min-h-[56px] items-center justify-between gap-2 px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-2.5">
            <Avatar className="h-9 w-9">
              {account?.avatar ? <AvatarImage src={coverThumb(account.avatar, 160)} alt={account.nickname} decoding="async" /> : null}
              <AvatarFallback>{account?.nickname.slice(0, 1) ?? '?'}</AvatarFallback>
            </Avatar>
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-1">
              <span className="max-w-[280px] truncate text-base font-semibold">{account?.nickname ?? '未绑定抖音账号'}</span>
              {/* v26：粉丝 / 关注 / 获赞 总量 */}
              {account ? (
                <span className="flex flex-wrap items-baseline gap-x-2.5 text-xs text-muted-foreground">
                  <span>
                    粉丝 <span className="tnum text-foreground">{account.followers == null ? '—' : formatCount(account.followers)}</span>
                  </span>
                  <span>
                    关注 <span className="tnum text-foreground">{account.following == null ? '—' : formatCount(account.following)}</span>
                  </span>
                  <span>
                    获赞 <span className="tnum text-foreground">{account.likes_total == null ? '—' : formatCount(account.likes_total)}</span>
                  </span>
                </span>
              ) : null}
            </div>
          </div>
          <Button variant="outline" size="sm" disabled={busy} onClick={onRefresh}>
            {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
            {busy ? '更新中…' : '更新数据'}
          </Button>
      </header>

      <div className="space-y-3 p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
          <Badge variant={data.private_available ? 'success' : 'secondary'}>
            {data.private_available ? '创作者数据可用' : '仅公开数据'}
          </Badge>
          <div className="flex items-center gap-1.5">
            <span>统计周期</span>
            <Select value={String(periodDays)} onValueChange={(value) => onPeriodChange(Number(value) as PeriodDays)}>
              <SelectTrigger className="h-8 w-[104px] text-xs" aria-label="统计周期">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {([7, 14, 30, 90] as const).map((days) => (
                  <SelectItem key={days} value={String(days)}>
                    近 {days} 日
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
                数据来自 TikHub 抖音创作者接口。统计周期可选 7/14/30/90 天：播放量/粉丝净增只在 7 日周期用官方账号诊断口径，其它周期与其它指标取本地每日快照差值（只覆盖近 120 天发布且已同步的作品，与抖音官方全账号口径可能不同）。点击任一指标可切换下方趋势曲线。
              </TooltipContent>
            </Tooltip>
          </div>
          <span>
            数据更新至：<span className="text-foreground">{formatDateTime(diagnosis?.captured_at)}</span>
          </span>
        </div>

        <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] lg:items-start">
          {/* 左：曲线 */}
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline justify-end gap-2">
              <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent" />
                {chartLabel}
              </span>
            </div>
            <div className="relative mt-1 min-h-[190px]">
              {/* 切指标时：旧曲线淡出、新曲线淡入，交叉过渡不闪 */}
              {fadeFrom ? (
                <motion.div
                  aria-hidden
                  className="pointer-events-none absolute inset-0"
                  initial={false}
                  animate={{ opacity: 0 }}
                  transition={{ duration: 0.26, ease: EASE_OUT_EXPO }}
                >
                  <TrendLine points={fadeFrom.points} ariaLabel="趋势" fillArea height={300} />
                </motion.div>
              ) : null}
              <motion.div
                key={`chart-${metricKey}`}
                initial={reduce || !fadeFrom ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.26, ease: EASE_OUT_EXPO }}
              >
                {series && points.filter((point) => point.value !== null).length >= 2 ? (
                  <TrendLine points={points} ariaLabel={`${chartLabel}趋势`} fillArea height={300} />
                ) : (
                  <Empty
                    className="mt-2"
                    text={`该指标在当前统计周期有效数据点不足（${points.filter((point) => point.value !== null).length} 个），无法绘制曲线`}
                  />
                )}
              </motion.div>
            </div>
          </div>

          {/* 右：数据（2 列，悬浮即切换左侧曲线） */}
          <motion.div
            key={`kpis-${periodDays}`}
            initial={reduce ? false : { opacity: 0.7, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={softIn}
            className="grid grid-cols-2 items-stretch gap-x-3 gap-y-2"
          >
            {data.kpis.map((kpi) => (
              <KpiCardView
                key={kpi.key}
                kpi={kpi}
                days={periodDays}
                active={metricKey === (kpi.trend_key ?? kpi.key)}
                onSelect={() => switchMetric(kpi.trend_key ?? kpi.key)}
              />
            ))}
          </motion.div>
        </div>
      </div>
    </section>
  )
}

function WarningBars({ data, onGoCreators }: { data: DashboardOverview; onGoCreators: () => void }) {
  const blocked = data.credential?.status === 'invalid' || data.data_policy?.source === 'blocked'
  const policyReason = data.data_policy?.reason || ''
  const warnings = data.warnings.filter((warning) => !(blocked && warning === policyReason))
  const hasNotice = blocked || !data.private_available || warnings.length > 0
  // v22：没有提示时不要渲染空 wrapper（空 div 会让下方 margin 塌陷，页面顶部比其它页多出 16px）
  if (!hasNotice) return null
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
  const [periodDays, setPeriodDays] = useState<PeriodDays>(7)
  const [metricKey, setMetricKey] = useState('plays')
  const [morePages, setMorePages] = useState<{ items: WorkItem[]; hasMore: boolean }>({ items: [], hasMore: false })
  const [loadingMore, setLoadingMore] = useState(false)
  const [overviewRunning, setOverviewRunning] = useState(false)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [postRunningId, setPostRunningId] = useState<number | null>(null)
  const [postError, setPostError] = useState<string | null>(null)
  const errorToasted = useRef(false)

  const overviewQ = useQuery({
    queryKey: ['dashboard', 'overview', periodDays],
    queryFn: () => apiJson<DashboardOverview>(`/api/douyin-dashboard/overview?period=${periodDays}`),
    // v7：切统计周期时保留上一周期数据，避免整页骨架闪一下
    placeholderData: keepPreviousData,
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

  // v10：进入页面默认选中「近期作品」第一条，直接展示作品分析详情
  useEffect(() => {
    if (selectedId !== null) return
    const firstItem = worksQ.data?.items?.[0]
    if (!firstItem) return
    setSelectedId(firstItem.post_id)
  }, [worksQ.data, selectedId])

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

  if (!overviewQ.data) {
    if (overviewQ.isPending) return <DashboardSkeleton />
    return <LoadError message={overviewQ.error instanceof Error ? overviewQ.error.message : '未知错误'} onRetry={() => void overviewQ.refetch()} />
  }
  const data = overviewQ.data
  if (!data.account) return <NoAccountState reason={data.blocked_reason} onGoCreators={() => navigate('/creators')} />

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0.85, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={softIn}
      className="space-y-4 pb-2"
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
          <AccountOverview
            data={data}
            busy={overviewBusy}
            onRefresh={() => void refreshOverview()}
            periodDays={periodDays}
            onPeriodChange={setPeriodDays}
            metricKey={metricKey}
            onMetricChange={setMetricKey}
          />
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
        <div className="pt-4">{worksQ.isPending ? <AnalysisSkeleton /> : <AnalysisGuide />}</div>
      )}
    </motion.div>
  )
}
