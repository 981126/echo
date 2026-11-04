// R-244 数据看板图表与共享展示件：项目无图表库，全部手写 SVG / CSS。
// 图表入场统一「从浅到深淡入」（不从 opacity:0 起步，避免闪一帧空白），
// 并尊重 prefers-reduced-motion（framermotion 的 useReducedMotion）。
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { ImageOff } from 'lucide-react'
import { CoverImage } from '@/components/ui/cover-image'
import { EASE_OUT_EXPO } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { formatPercent } from './format'
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
          {hint ? <p className="mt-0.5 text-xs md:text-[11px] leading-4 text-muted-foreground">{hint}</p> : null}
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
      <div className="flex items-center gap-1.5 text-xs md:text-[11px] text-muted-foreground">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div className="tnum mt-1 text-base font-semibold leading-6">{value}</div>
      {hint ? <div className="mt-0.5 text-xs md:text-[10px] leading-4 text-muted-foreground">{hint}</div> : null}
    </div>
  )
}

/** 封面缩略图：本地 /covers/ 走 coverThumb 缩略；加载失败显示占位块 */
export function Thumb({ url, alt, className }: { url: string | null | undefined; alt: string; className?: string }) {
  return (
    <div className={cn('overflow-hidden bg-muted', className)}>
      <CoverImage
        url={url}
        alt={alt}
        width={240}
        className="h-full w-full object-cover"
        placeholder={<div className="flex h-full w-full items-center justify-center text-muted-foreground/70"><ImageOff className="h-4 w-4" /></div>}
      />
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

/** Catmull-Rom → 三次贝塞尔平滑路径（缺口处直接跨过，用平滑线过渡，不画孤立点） */
function smoothPath(points: Array<[number, number]>): string {
  if (points.length === 0) return ''
  if (points.length === 1) return `M${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`
  const tension = 0.9
  let d = `M${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`
  for (let index = 0; index < points.length - 1; index += 1) {
    const p0 = points[index - 1] ?? points[index]
    const p1 = points[index]
    const p2 = points[index + 1]
    const p3 = points[index + 2] ?? p2
    const c1x = p1[0] + ((p2[0] - p0[0]) / 6) * tension
    const c1y = p1[1] + ((p2[1] - p0[1]) / 6) * tension
    const c2x = p2[0] - ((p3[0] - p1[0]) / 6) * tension
    const c2y = p2[1] - ((p3[1] - p1[1]) / 6) * tension
    d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`
  }
  return d
}

interface TrendLineProps {
  points: TrendLinePoint[]
  ariaLabel: string
  height?: number
  /** 抖音账号总览同款：折线下方浅色面积（默认关闭，作品详情趋势保持纯线） */
  fillArea?: boolean
  emptyText?: string
  /** 纵轴刻度格式化（比率指标传百分比格式，避免出现 0/1 而不是 30%/47%） */
  axisFormat?: (value: number) => string
}

/** 趋势曲线：跳过空值、用平滑线连接有效点（不在缺口处断开、不画孤立点）。 */
export function TrendLine({
  points,
  ariaLabel,
  height = 190,
  fillArea = false,
  emptyText = '暂无可绘制的数据点',
  axisFormat
}: TrendLineProps) {
  const reduce = useReducedMotion()
  const valid = points
    .map((point, index) => ({ index, value: point.value }))
    .filter((point): point is { index: number; value: number } => typeof point.value === 'number')
  if (valid.length < 2) return <Empty text={emptyText} />
  // 支持负值（如「净增粉丝」逐日可负数）：纵轴域 = [min, max]，0 不在底部时画零参考线
  const values = valid.map((point) => point.value)
  const rawMax = Math.max(...values)
  const rawMin = Math.min(...values)
  const max = niceMax(Math.max(rawMax, 1))
  const min = rawMin < 0 ? -niceMax(-rawMin) : 0
  const span = max - min || 1
  const innerW = LINE_W - LINE_LEFT - LINE_RIGHT
  const innerH = height - LINE_TOP - LINE_BOTTOM
  const xAt = (index: number) => LINE_LEFT + (points.length <= 1 ? innerW / 2 : (index / (points.length - 1)) * innerW)
  const yAt = (value: number) => LINE_TOP + ((max - value) / span) * innerH
  const ticks = Array.from({ length: 5 }, (_, index) => max - (span * index) / 4)
  const coords = valid.map((point) => [xAt(point.index), yAt(point.value)] as [number, number])
  const linePath = smoothPath(coords)
  const zeroY = yAt(0)
  const areaPath = `${linePath} L${coords[coords.length - 1][0].toFixed(1)} ${zeroY.toFixed(1)} L${coords[0][0].toFixed(1)} ${zeroY.toFixed(1)} Z`

  return (
    <svg viewBox={`0 0 ${LINE_W} ${height}`} className="w-full" role="img" aria-label={ariaLabel}>
      <title>{ariaLabel}</title>
      {ticks.map((tick, index) => {
        const y = yAt(tick)
        return (
          <g key={index}>
            <line
              x1={LINE_LEFT}
              x2={LINE_W - LINE_RIGHT}
              y1={y}
              y2={y}
              stroke="var(--border)"
              strokeDasharray={index === ticks.length - 1 || (min < 0 && Math.abs(tick) < 1e-9) ? undefined : '3 4'}
            />
            <text x={LINE_LEFT - 6} y={y + 3.5} textAnchor="end" fill="var(--muted-foreground)" fontSize="10">
              {(axisFormat ?? axisText)(tick)}
            </text>
          </g>
        )
      })}
      {min < 0 ? <line x1={LINE_LEFT} x2={LINE_W - LINE_RIGHT} y1={zeroY} y2={zeroY} stroke="var(--muted-foreground)" strokeOpacity={0.55} /> : null}
      {fillArea ? (
        <motion.path
          d={areaPath}
          fill="var(--accent)"
          fillOpacity={0.1}
          stroke="none"
          initial={reduce ? false : { opacity: 0.7 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3, ease: EASE_OUT_EXPO }}
        />
      ) : null}
      <motion.path
        d={linePath}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={reduce ? false : { opacity: 0.7 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, ease: EASE_OUT_EXPO }}
      />
      {points.map((point, index) => {
        // 长周期（14/30/90 天）横轴只显示约 7 个日期，避免标签重叠
        const step = Math.max(1, Math.ceil(points.length / 7))
        const visible = index === 0 || index === points.length - 1 || index % step === 0
        if (!visible) return null
        return (
          <text key={`x-${index}`} x={xAt(index)} y={height - 8} textAnchor="middle" fill="var(--muted-foreground)" fontSize="10">
            {point.label}
          </text>
        )
      })}
    </svg>
  )
}

type TrendSnapshot = { key: string; props: TrendLineProps }

export function CrossfadeTrendLine({ transitionKey, ...props }: TrendLineProps & { transitionKey: string }) {
  const reduce = useReducedMotion()
  const currentRef = useRef<TrendSnapshot>({ key: transitionKey, props })
  const previousRef = useRef(currentRef.current)
  const [fadeFrom, setFadeFrom] = useState<TrendSnapshot | null>(null)
  currentRef.current = { key: transitionKey, props }
  const previous = previousRef.current
  const outgoing = previous.key !== transitionKey ? previous : fadeFrom

  useLayoutEffect(() => {
    const current = currentRef.current
    const previous = previousRef.current
    if (previous.key === current.key) return
    previousRef.current = current
    setFadeFrom(previous)
    const timer = window.setTimeout(() => setFadeFrom(null), 280)
    return () => window.clearTimeout(timer)
  }, [transitionKey])

  return (
    <div className="relative">
      {!reduce && outgoing ? (
        <motion.div
          key={`outgoing-${outgoing.key}`}
          data-testid="trend-outgoing"
          aria-hidden
          className="pointer-events-none absolute inset-0"
          initial={{ opacity: 1 }}
          animate={{ opacity: 0 }}
          transition={{ duration: 0.26, ease: EASE_OUT_EXPO }}
        >
          <TrendLine {...outgoing.props} />
        </motion.div>
      ) : null}
      <motion.div
        key={`current-${transitionKey}`}
        data-testid="trend-current"
        initial={reduce || !outgoing ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.26, ease: EASE_OUT_EXPO }}
      >
        <TrendLine {...props} />
      </motion.div>
    </div>
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
        <motion.g initial={reduce ? false : { opacity: 0.7 }} animate={{ opacity: 1 }} transition={{ duration: 0.3, ease: EASE_OUT_EXPO }}>
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
      {items.map((item) => (
        <div key={item.label} className="flex min-w-0 flex-1 flex-col items-center gap-1">
          <span className="tnum text-xs md:text-[10px] text-muted-foreground">{formatPercent(item.ratio)}</span>
          <motion.div
            initial={reduce ? false : { opacity: 0.7 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3, ease: EASE_OUT_EXPO }}
            style={{ height: `${6 + (item.ratio / max) * 104}px` }}
            className="w-full max-w-10 rounded-t-md bg-accent/85"
          />
          <span className="w-full truncate text-center text-xs md:text-[10px] text-muted-foreground" title={item.label}>{item.label}</span>
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
              initial={reduce ? false : { opacity: 0.7 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3, ease: EASE_OUT_EXPO }}
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
        <motion.g initial={reduce ? false : { opacity: 0.7 }} animate={{ opacity: 1 }} transition={{ duration: 0.3, ease: EASE_OUT_EXPO }}>
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
      <div className="mt-2 flex flex-wrap items-center gap-4 text-xs md:text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-5 rounded-full bg-accent" />当前作品</span>
        <span className="flex items-center gap-1.5"><span className="w-5 border-t border-dashed border-muted-foreground" />同类作者参考</span>
      </div>
    </div>
  )
}
