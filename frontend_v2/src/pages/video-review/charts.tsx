import { useState, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import { BarChart3, Clock3, Eye, Heart, MessageCircle, Play, Table2, TrendingDown, UserPlus } from 'lucide-react'
import type { Charts, Metric } from './types'
import { cn } from '@/lib/utils'

export function formatMetric(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '暂无数据'
  if (unit === 'ratio') return `${(value * 100).toFixed(1)}%`
  if (unit === '秒') return `${value.toFixed(value >= 100 ? 0 : 1)}秒`
  return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value)}${unit === '人' ? '人' : unit}`
}

export function metricStateText(metric: Metric, arrow = false): string {
  if (metric.missing) return '暂无历史对比'
  if (metric.state === 'limited') return '样本较少'
  if (metric.state === 'high') return arrow ? '↑ 高于平时' : '高于平时'
  if (metric.state === 'low') return arrow ? '↓ 低于平时' : '低于平时'
  return '接近平时'
}

function ChartFrame({ title, conclusion, headers, rows, children }: { title: string; conclusion?: string; headers: string[]; rows: Array<Array<string | number>>; children: ReactNode }) {
  const [table, setTable] = useState(false)
  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-card">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          {conclusion && <p className="mt-1 text-xs leading-5 text-muted-foreground">{conclusion}</p>}
        </div>
        <button type="button" onClick={() => setTable((v) => !v)} className="flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground">
          {table ? <BarChart3 className="h-3.5 w-3.5" /> : <Table2 className="h-3.5 w-3.5" />}
          {table ? '看图' : '数据表'}
        </button>
      </div>
      {table ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-xs">
            <thead><tr className="border-b border-border text-muted-foreground">{headers.map((x) => <th key={x} className="px-2 py-2 font-medium">{x}</th>)}</tr></thead>
            <tbody>{rows.map((row, i) => <tr key={i} className="border-b border-border/60 last:border-0">{row.map((cell, j) => <td key={j} className="px-2 py-2">{cell}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ) : children}
    </section>
  )
}

const metricIcons: Record<string, ReactNode> = {
  plays: <Play className="h-4 w-4" />, likes: <Heart className="h-4 w-4" />, comments: <MessageCircle className="h-4 w-4" />,
  finish_rate: <Clock3 className="h-4 w-4" />, finish_5s_rate: <Clock3 className="h-4 w-4" />, bounce_2s_rate: <TrendingDown className="h-4 w-4" />,
  profile_visits: <Eye className="h-4 w-4" />, follower_gain: <UserPlus className="h-4 w-4" />, follower_per_1k: <UserPlus className="h-4 w-4" />
}

export function MetricCards({ metrics }: { metrics: Metric[] }) {
  const preferred = ['plays', 'likes', 'finish_rate', 'follower_gain', 'bounce_2s_rate', 'finish_5s_rate', 'avg_play_seconds', 'profile_visits']
  const selected = preferred.map((key) => metrics.find((m) => m.key === key)).filter((x): x is Metric => Boolean(x))
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {selected.map((metric) => (
        <motion.div key={metric.key} initial={{ opacity: 0.7, y: 5 }} animate={{ opacity: 1, y: 0 }} className="rounded-xl border border-border bg-card p-4 shadow-card">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">{metricIcons[metric.key] ?? <BarChart3 className="h-4 w-4" />}<span>{metric.label}</span></div>
          <div className="tnum mt-3 text-xl font-semibold">{formatMetric(metric.value, metric.unit)}</div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            平时 {formatMetric(metric.baseline, metric.unit)} · {metricStateText(metric)}
          </div>
        </motion.div>
      ))}
    </div>
  )
}

export function BaselineBars({ metrics, title = '这条视频和平时相比，差别有多大？' }: { metrics: Metric[]; title?: string }) {
  const visible = metrics.filter((m) => !m.missing && m.value !== null && m.baseline !== null)
  return (
    <ChartFrame title={title} conclusion="蓝色是这条视频，灰色是相近视频在相同发布天数下的平时中位数。" headers={['指标', '这条视频', '平时', '判断']} rows={visible.map((m) => [m.label, formatMetric(m.value, m.unit), formatMetric(m.baseline, m.unit), metricStateText(m)])}>
      <div className="space-y-4">
        {visible.map((metric) => {
          const max = Math.max(metric.value ?? 0, metric.baseline ?? 0, 0.0001)
          return (
            <div key={metric.key}>
              <div className="mb-1.5 flex items-center justify-between text-xs"><span>{metric.label}{metric.key === 'bounce_2s_rate' ? '（越低越好）' : ''}</span><span className={cn('tnum font-medium', metric.state === 'high' && 'text-emerald-600', metric.state === 'low' && 'text-amber-600')}>{metricStateText(metric, true)}</span></div>
              <div className="space-y-1.5">
                <div className="flex items-center gap-2"><span className="w-9 text-[10px] text-muted-foreground">这条</span><div className="h-3 flex-1 rounded-full bg-muted"><motion.div initial={{ width: 0 }} animate={{ width: `${Math.max(2, ((metric.value ?? 0) / max) * 100)}%` }} className="h-3 rounded-full bg-indigo-500" /></div><span className="tnum w-20 text-right text-[11px]">{formatMetric(metric.value, metric.unit)}</span></div>
                <div className="flex items-center gap-2"><span className="w-9 text-[10px] text-muted-foreground">平时</span><div className="h-3 flex-1 rounded-full bg-muted"><div style={{ width: `${Math.max(2, ((metric.baseline ?? 0) / max) * 100)}%` }} className="h-3 rounded-full bg-zinc-300 dark:bg-zinc-600" /></div><span className="tnum w-20 text-right text-[11px]">{formatMetric(metric.baseline, metric.unit)}</span></div>
              </div>
            </div>
          )
        })}
      </div>
    </ChartFrame>
  )
}

export function WatchTrendChart({ data }: { data: Charts['retention'] }) {
  const points = data.points.filter((p) => typeof p.current === 'number')
  if (!points.length) return <ChartFrame title="观众在哪些时间点继续看或离开？" headers={['时间', '留存']} rows={[]}><div className="py-12 text-center text-sm text-muted-foreground">暂无观看趋势数据</div></ChartFrame>
  const width = 720, height = 220, left = 42, right = 18, top = 18, bottom = 36
  const maxTime = Math.max(...points.map((p) => p.time_seconds), 1)
  const xy = (p: { time_seconds: number; current?: number; similar_author?: number }, key: 'current' | 'similar_author') => {
    const value = p[key]
    return [left + (p.time_seconds / maxTime) * (width - left - right), top + (1 - (typeof value === 'number' ? value : 0)) * (height - top - bottom)] as const
  }
  const path = (key: 'current' | 'similar_author') => points.filter((p) => typeof p[key] === 'number').map((p, i) => `${i ? 'L' : 'M'}${xy(p, key).join(',')}`).join(' ')
  const drops = points.slice(1).map((p, i) => ({ index: i + 1, value: (points[i].current ?? 0) - (p.current ?? 0) }))
  const biggest = drops.reduce((a, b) => (b.value > a.value ? b : a), { index: 0, value: 0 })
  return (
    <ChartFrame title="观众在哪些时间点继续看或离开？" conclusion={data.reliable ? '实线是当前视频，虚线是平台同类作者参考。异常下降点会直接标出。' : '播放量较少，趋势仅供参考。'} headers={['时间', '当前视频', '同类参考']} rows={points.map((p) => [p.time_label, formatMetric(p.current, 'ratio'), formatMetric(p.similar_author, 'ratio')])}>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="min-w-[560px]" role="img" aria-label="观看趋势折线图">
          <title>观看趋势：当前视频与同类作者参考</title><desc>横轴为视频时间，纵轴为留存比例</desc>
          {[0, 0.25, 0.5, 0.75, 1].map((v) => <g key={v}><line x1={left} x2={width - right} y1={top + (1 - v) * (height - top - bottom)} y2={top + (1 - v) * (height - top - bottom)} stroke="var(--border)" /><text x={4} y={top + (1 - v) * (height - top - bottom) + 4} fill="var(--muted-foreground)" fontSize="10">{v * 100}%</text></g>)}
          <motion.path initial={{ opacity: 0.7 }} animate={{ opacity: 1 }} d={path('current')} fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinejoin="round" />
          <path d={path('similar_author')} fill="none" stroke="var(--muted-foreground)" strokeWidth="2" strokeDasharray="6 5" />
          {points.map((p, i) => <g key={i}><circle cx={xy(p, 'current')[0]} cy={xy(p, 'current')[1]} r={i === biggest.index && biggest.value >= 0.05 ? 5 : 2.5} fill={i === biggest.index && biggest.value >= 0.05 ? 'var(--warning)' : 'var(--accent)'}><title>{`${p.time_label}：当前${formatMetric(p.current, 'ratio')}，同类${formatMetric(p.similar_author, 'ratio')}`}</title></circle>{i === biggest.index && biggest.value >= 0.05 && <text x={Math.min(width - 130, xy(p, 'current')[0] + 8)} y={Math.max(14, xy(p, 'current')[1] - 10)} fill="var(--warning)" fontSize="11">下降{(biggest.value * 100).toFixed(1)}个百分点</text>}</g>)}
          {points.map((p, i) => (i === 0 || i === points.length - 1 || i === Math.floor(points.length / 2)) && <text key={`t${i}`} x={xy(p, 'current')[0] - 12} y={height - 8} fill="var(--muted-foreground)" fontSize="10">{p.time_label}</text>)}
        </svg>
      </div>
    </ChartFrame>
  )
}

export function SimpleBars({ title, conclusion, items, unit = '次' }: { title: string; conclusion?: string; items: Array<{ label: string; value: number; detail?: string }>; unit?: string }) {
  const max = Math.max(...items.map((x) => x.value), 1)
  return (
    <ChartFrame title={title} conclusion={conclusion} headers={['项目', '数值', '说明']} rows={items.map((x) => [x.label, x.value, x.detail ?? ''])}>
      {items.length ? <div className="space-y-3">{items.map((item) => <div key={item.label} className="grid grid-cols-[minmax(90px,0.8fr)_2fr_auto] items-center gap-3 text-xs"><span className="truncate" title={item.label}>{item.label}</span><div className="h-2.5 rounded-full bg-muted"><motion.div initial={{ width: 0 }} animate={{ width: `${Math.max(2, item.value / max * 100)}%` }} className="h-2.5 rounded-full bg-indigo-500" /></div><span className="tnum text-right">{item.value.toLocaleString('zh-CN')}{unit}<span className="ml-1 text-muted-foreground">{item.detail}</span></span></div>)}</div> : <div className="py-8 text-center text-sm text-muted-foreground">暂无数据</div>}
    </ChartFrame>
  )
}

export function PlanComparisonCharts({ items }: { items: Charts['plan'] }) {
  return (
    <ChartFrame title="上次修改以后，数据有没有改善？" conclusion="每项指标独立比较，不把不同单位放在同一坐标轴。" headers={['指标', '修改前', '修改后', '结果']} rows={items.map((x) => [x.label, formatMetric(x.before, x.unit), formatMetric(x.after, x.unit), x.result === 'improved' ? '改善' : x.result === 'not_improved' ? '未改善' : '暂时不能确定'])}>
      <div className="grid gap-3 md:grid-cols-2">{items.map((item) => {
        const before = item.before ?? 0, after = item.after ?? 0, max = Math.max(before, after, 0.001)
        return <div key={item.metric} className="rounded-lg border border-border p-3"><div className="flex justify-between text-xs"><span>{item.label}</span><span className={cn(item.result === 'improved' ? 'text-emerald-600' : 'text-amber-600')}>{item.result === 'improved' ? '改善' : item.result === 'not_improved' ? '未改善' : '暂时不能确定'}</span></div><div className="mt-3 space-y-2"><div className="h-2 rounded bg-muted"><div style={{ width: `${before / max * 100}%` }} className="h-2 rounded bg-zinc-300 dark:bg-zinc-600" /></div><div className="h-2 rounded bg-muted"><div style={{ width: `${after / max * 100}%` }} className="h-2 rounded bg-indigo-500" /></div></div><div className="tnum mt-2 text-xs text-muted-foreground">{formatMetric(item.before, item.unit)} → {formatMetric(item.after, item.unit)}</div></div>
      })}</div>
    </ChartFrame>
  )
}
