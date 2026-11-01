// R-244 数据看板图表与共享展示件：项目无图表库，全部手写 SVG / CSS。
// 图表入场统一「从浅到深淡入」（不从 opacity:0 起步，避免闪一帧空白），
// 并尊重 prefers-reduced-motion（framermotion 的 useReducedMotion）。
import { useState, type ReactNode } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { ImageOff } from 'lucide-react'
import { coverThumb } from '@/lib/covers'
import { cn } from '@/lib/utils'
import { formatCount, formatPercent } from './format'
import type { WatchPoint } from './types'

const CHART_COLORS = ['var(--accent)', '#a78bfa', 'var(--warning)', 'var(--success)', '#f472b6', '#38bdf8']

/** 区块卡片外壳（标题 + 说明 + 右上操作） */
export function Panel({
  title,
  hint,
  extra,
  children,
  className
}: {
  title: string
  hint?: ReactNode
  extra?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('rounded-xl border border-border bg-card p-3.5 shadow-[var(--shadow-card)] sm:p-4', className)}>
      <div className="mb-2.5 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          {hint ? <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{hint}</p> : null}
        </div>
        {extra}
      </div>
      {children}
    </section>
  )
}

/** 区块级空状态：严格区分「暂无数据」与真实 0 */
export function Empty({ text = '暂无数据', children, className }: { text?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-3 py-8 text-center text-xs text-muted-foreground', className)}>
      <span>{text}</span>
      {children}
    </div>
  )
}

/** 指标小块（数字卡） */
export function StatTile({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-2.5 py-2">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div className="tnum mt-1 text-base font-semibold leading-6">{value}</div>
      {hint ? <div className="mt-0.5 text-[10px] leading-4 text-muted-foreground">{hint}</div> : null}
    </div>
  )
}

/** 封面缩略图：本地 /covers/ 走 coverThumb 缩略；加载失败显示占位块 */
export function Thumb({ url, alt, className }: { url: string | null | undefined; alt: string; className?: string }) {
  const [failed, setFailed] = useState(false)
  const src = coverThumb(url, 240)
  return (
    <div className={cn('overflow-hidden bg-muted', className)}>
      {src && !failed ? (
        <img src={src} alt={alt} loading="lazy" decoding="async" onError={() => setFailed(true)} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-muted-foreground/70">
          <ImageOff className="h-4 w-4" />
        </div>
      )}
    </div>
  )
}

function niceMax(max: number): number {
  if (!Number.isFinite(max) || max <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(max))
  const normalized = max / magnitude
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  return step * magnitude
}

function axisText(value: number): string {
  if (value === 0) return '0'
  if (value >= 100_000_000) return `${Number((value / 100_000_000).toFixed(1))}亿`
  if (value >= 10_000) return `${Number((value / 10_000).toFixed(1))}万`
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value)
}

export interface TrendLinePoint {
  /** 横轴短标签（MM-DD） */
  label: string
  /** null = 当天算不出（曲线断开，不补 0） */
  value: number | null
}

const LINE_W = 640
const LINE_LEFT = 46
const LINE_RIGHT = 14
const LINE_TOP = 16
const LINE_BOTTOM = 26

/** 逐日趋势折线：null 断开、不插值；纵轴自动取整刻度。 */
export function TrendLine({
  points,
  ariaLabel,
  height = 190,
  fillArea = false
}: {
  points: TrendLinePoint[]
  ariaLabel: string
  height?: number
  /** 抖音账号总览同款：折线下方浅色面积（默认关闭，作品详情趋势保持纯线） */
  fillArea?: boolean
}) {
  const reduce = useReducedMotion()
  const values = points.map((point) => point.value).filter((value): value is number => typeof value === 'number')
  if (!values.length) return <Empty />
  const max = niceMax(Math.max(...values))
  const innerW = LINE_W - LINE_LEFT - LINE_RIGHT
  const innerH = height - LINE_TOP - LINE_BOTTOM
  const xAt = (index: number) => LINE_LEFT + (points.length <= 1 ? innerW / 2 : (index / (points.length - 1)) * innerW)
  const yAt = (value: number) => LINE_TOP + (1 - value / max) * innerH

  // 连续有值的点连成一段，遇到 null 断开
  const segments: Array<Array<{ index: number; value: number }>> = []
  let segment: Array<{ index: number; value: number }> = []
  points.forEach((point, index) => {
    if (typeof point.value === 'number') {
      segment.push({ index, value: point.value })
    } else if (segment.length) {
      segments.push(segment)
      segment = []
    }
  })
  if (segment.length) segments.push(segment)

  return (
    <svg viewBox={`0 0 ${LINE_W} ${height}`} className="w-full" role="img" aria-label={ariaLabel}>
      <title>{ariaLabel}</title>
      {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const y = LINE_TOP + (1 - ratio) * innerH
        return (
          <g key={ratio}>
            <line x1={LINE_LEFT} x2={LINE_W - LINE_RIGHT} y1={y} y2={y} stroke="var(--border)" strokeDasharray={ratio === 0 ? undefined : '3 4'} />
            <text x={LINE_LEFT - 6} y={y + 3.5} textAnchor="end" fill="var(--muted-foreground)" fontSize="10">
              {axisText(max * ratio)}
            </text>
          </g>
        )
      })}
      {fillArea
        ? segments.map((seg, index) => {
            if (seg.length < 2) return null
            const bottom = height - LINE_BOTTOM
            const first = seg[0]
            const last = seg[seg.length - 1]
            const areaD = [
              `M${xAt(first.index).toFixed(1)} ${bottom.toFixed(1)}`,
              `L${xAt(first.index).toFixed(1)} ${yAt(first.value).toFixed(1)}`,
              ...seg.slice(1).map((point) => `L${xAt(point.index).toFixed(1)} ${yAt(point.value).toFixed(1)}`),
              `L${xAt(last.index).toFixed(1)} ${bottom.toFixed(1)}`,
              'Z'
            ].join(' ')
            return (
              <motion.path
                key={`area-${index}`}
                d={areaD}
                fill="var(--accent)"
                fillOpacity={0.1}
                stroke="none"
                initial={reduce ? false : { opacity: 0.7 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.4 }}
              />
            )
          })
        : null}
      {segments.map((seg, index) =>
        seg.length > 1 ? (
          <motion.path
            key={`line-${index}`}
            d={seg.map((point, i) => `${i ? 'L' : 'M'}${xAt(point.index).toFixed(1)} ${yAt(point.value).toFixed(1)}`).join(' ')}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduce ? false : { opacity: 0.65 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3 }}
          />
        ) : null
      )}
      {segments.map((seg) =>
        seg.map((point) => (
          <circle key={`dot-${point.index}`} cx={xAt(point.index)} cy={yAt(point.value)} r={2.6} fill="var(--accent)">
            <title>{`${points[point.index].label}：${formatCount(point.value)}`}</title>
          </circle>
        ))
      )}
      {points.map((point, index) => (
        <text key={`x-${index}`} x={xAt(index)} y={height - 8} textAnchor="middle" fill="var(--muted-foreground)" fontSize="10">
          {point.label}
        </text>
      ))}
    </svg>
  )
}

/** 环形分布图（性别 / 活跃度）：占比按总和归一后绘制 */
export function Donut({ items, ariaLabel }: { items: Array<{ label: string; ratio: number }>; ariaLabel: string }) {
  const reduce = useReducedMotion()
  const valid = items.filter((item) => Number.isFinite(item.ratio) && item.ratio > 0)
  const total = valid.reduce((sum, item) => sum + item.ratio, 0)
  if (!valid.length || total <= 0) return <Empty />
  const radius = 42
  const circumference = 2 * Math.PI * radius
  let offset = 0
  const segments = valid.map((item, index) => {
    const ratio = item.ratio / total
    const segment = { label: item.label, ratio, offset, color: CHART_COLORS[index % CHART_COLORS.length] }
    offset += ratio
    return segment
  })
  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 100 100" className="h-28 w-28 shrink-0" role="img" aria-label={ariaLabel}>
        <title>{ariaLabel}</title>
        <circle cx="50" cy="50" r={radius} fill="none" stroke="var(--muted)" strokeWidth="13" />
        <motion.g initial={reduce ? false : { opacity: 0.65 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
          <g transform="rotate(-90 50 50)">
            {segments.map((seg) => (
              <circle
                key={seg.label}
                cx="50"
                cy="50"
                r={radius}
                fill="none"
                stroke={seg.color}
                strokeWidth="13"
                strokeDasharray={`${seg.ratio * circumference} ${circumference}`}
                strokeDashoffset={-seg.offset * circumference}
              />
            ))}
          </g>
        </motion.g>
      </svg>
      <ul className="min-w-0 flex-1 space-y-1.5">
        {segments.map((seg) => (
          <li key={seg.label} className="flex items-center justify-between gap-3 text-xs">
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: seg.color }} />
              <span className="truncate" title={seg.label}>{seg.label}</span>
            </span>
            <span className="tnum shrink-0 text-muted-foreground">{formatPercent(seg.ratio)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** 柱状分布（年龄）：HTML/CSS 柱，等比高度 */
export function Bars({ items, ariaLabel }: { items: Array<{ label: string; ratio: number }>; ariaLabel?: string }) {
  const reduce = useReducedMotion()
  if (!items.length) return <Empty />
  const max = Math.max(...items.map((item) => item.ratio), 0.0001)
  return (
    <div role="img" aria-label={ariaLabel ?? '柱状分布图'} className="flex items-end justify-between gap-2 pt-4">
      {items.map((item, index) => (
        <div key={item.label} className="flex min-w-0 flex-1 flex-col items-center gap-1">
          <span className="tnum text-[10px] text-muted-foreground">{formatPercent(item.ratio)}</span>
          <motion.div
            initial={reduce ? false : { opacity: 0.55 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.28, delay: reduce ? 0 : index * 0.03 }}
            style={{ height: `${6 + (item.ratio / max) * 104}px` }}
            className="w-full max-w-10 rounded-t-md bg-accent/85"
          />
          <span className="w-full truncate text-center text-[10px] text-muted-foreground" title={item.label}>{item.label}</span>
        </div>
      ))}
    </div>
  )
}

/** 占比条列表（流量来源 / 地域 / 兴趣）：名称 + 条 + 百分比 */
export function RatioRows({
  items,
  ariaLabel
}: {
  items: Array<{ label: string; ratio: number; muted?: boolean }>
  ariaLabel?: string
}) {
  const reduce = useReducedMotion()
  if (!items.length) return <Empty />
  const max = Math.max(...items.map((item) => item.ratio), 0.0001)
  return (
    <ul aria-label={ariaLabel} className="space-y-2">
      {items.map((item, index) => (
        <li key={`${item.label}-${index}`} className="grid grid-cols-[minmax(52px,88px)_minmax(0,1fr)_auto] items-center gap-2 text-xs">
          <span className={cn('truncate', item.muted && 'text-muted-foreground')} title={item.label}>{item.label}</span>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <motion.div
              initial={reduce ? false : { opacity: 0.55 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.28, delay: reduce ? 0 : index * 0.02 }}
              style={{ width: `${Math.max(2, (item.ratio / max) * 100)}%` }}
              className={cn('h-2 rounded-full', item.muted ? 'bg-zinc-300 dark:bg-zinc-600' : 'bg-accent/85')}
            />
          </div>
          <span className="tnum shrink-0 text-right text-muted-foreground">{formatPercent(item.ratio)}</span>
        </li>
      ))}
    </ul>
  )
}

const WATCH_W = 640
const WATCH_H = 200
const WATCH_LEFT = 42
const WATCH_RIGHT = 14
const WATCH_TOP = 14
const WATCH_BOTTOM = 24

function watchPath(points: WatchPoint[], key: 'current' | 'similar', xAt: (index: number) => number, yAt: (value: number) => number): string {
  let d = ''
  let started = false
  points.forEach((point, index) => {
    const value = point[key]
    if (typeof value !== 'number') {
      started = false
      return
    }
    d += `${started ? 'L' : 'M'}${xAt(index).toFixed(1)} ${yAt(value).toFixed(1)} `
    started = true
  })
  return d
}

/** 观看趋势：当前作品实线 + 同类作者参考虚线，横轴为播放进度 key、纵轴百分比 */
export function WatchTrend({ points, ariaLabel }: { points: WatchPoint[]; ariaLabel?: string }) {
  const reduce = useReducedMotion()
  const hasCurrent = points.some((point) => typeof point.current === 'number')
  const hasSimilar = points.some((point) => typeof point.similar === 'number')
  if (!hasCurrent && !hasSimilar) return <Empty />
  const innerW = WATCH_W - WATCH_LEFT - WATCH_RIGHT
  const innerH = WATCH_H - WATCH_TOP - WATCH_BOTTOM
  const xAt = (index: number) => WATCH_LEFT + (points.length <= 1 ? innerW / 2 : (index / (points.length - 1)) * innerW)
  const yAt = (value: number) => WATCH_TOP + (1 - value) * innerH
  const labelIndexes = points.length <= 3 ? points.map((_, index) => index) : [0, Math.floor((points.length - 1) / 2), points.length - 1]
  return (
    <div>
      <svg viewBox={`0 0 ${WATCH_W} ${WATCH_H}`} className="w-full" role="img" aria-label={ariaLabel ?? '观看趋势折线图'}>
        <title>{ariaLabel ?? '观看趋势折线图'}</title>
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = WATCH_TOP + (1 - ratio) * innerH
          return (
            <g key={ratio}>
              <line x1={WATCH_LEFT} x2={WATCH_W - WATCH_RIGHT} y1={y} y2={y} stroke="var(--border)" strokeDasharray={ratio === 0 ? undefined : '3 4'} />
              <text x={WATCH_LEFT - 6} y={y + 3.5} textAnchor="end" fill="var(--muted-foreground)" fontSize="10">
                {ratio * 100}%
              </text>
            </g>
          )
        })}
        <motion.g initial={reduce ? false : { opacity: 0.65 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
          {hasSimilar ? <path d={watchPath(points, 'similar', xAt, yAt)} fill="none" stroke="var(--muted-foreground)" strokeWidth={2} strokeDasharray="6 5" strokeLinecap="round" /> : null}
          {hasCurrent ? <path d={watchPath(points, 'current', xAt, yAt)} fill="none" stroke="var(--accent)" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" /> : null}
          {points.map((point, index) =>
            typeof point.current === 'number' ? (
              <circle key={`watch-${point.key}`} cx={xAt(index)} cy={yAt(point.current)} r={2.4} fill="var(--accent)">
                <title>{`${point.key}：当前 ${formatPercent(point.current)}，同类 ${formatPercent(point.similar)}`}</title>
              </circle>
            ) : null
          )}
        </motion.g>
        {labelIndexes.map((index) => (
          <text key={`watch-x-${index}`} x={xAt(index)} y={WATCH_H - 7} textAnchor={index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'} fill="var(--muted-foreground)" fontSize="10">
            {points[index].key}
          </text>
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-4 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 rounded-full bg-accent" />当前作品</span>
        <span className="flex items-center gap-1.5"><span className="w-5 border-t border-dashed border-muted-foreground" />同类作者参考</span>
      </div>
    </div>
  )
}
