// R-244 数据看板展示格式化：纯函数，不依赖 DOM/时区，便于单测。
// 规则统一：缺失（null/undefined/NaN）显示「暂无数据」；平台明确返回 0 时显示 0，两者不可混淆。

export const MISSING_TEXT = '暂无数据'

/** 状态徽标色调：与 components/ui/badge 的 variant 对应 */
export type StatusTone = 'default' | 'secondary' | 'success' | 'destructive' | 'warning'

export function isMissing(value: number | null | undefined): boolean {
  return value === null || value === undefined || Number.isNaN(value)
}

/** 大数字：≥1 亿 →「x.x 亿」；≥1 万 →「x.x 万」；否则整数（千分位）。null → 暂无数据，0 → 0。 */
export function formatCount(value: number | null | undefined): string {
  if (isMissing(value)) return MISSING_TEXT
  const v = value as number
  const sign = v < 0 ? '-' : ''
  const abs = Math.abs(v)
  if (abs >= 100_000_000) return `${sign}${(abs / 100_000_000).toFixed(1)}亿`
  if (abs >= 10_000) return `${sign}${(abs / 10_000).toFixed(1)}万`
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(v)
}

/** 热度（受众关注热词近 7 日 query_cnt_7d）：口径与大数字一致，≥1 亿 → 亿，≥1 万 → 万。 */
export function formatHeat(value: number | null | undefined): string {
  return formatCount(value)
}

/** 比率（后端 0~1 小数）→ 百分比字符串；digits 控制小数位。null → 暂无数据，0 → 0.0%。 */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (isMissing(value)) return MISSING_TEXT
  return `${((value as number) * 100).toFixed(digits)}%`
}

/** 同类排名分位（0~1）→「66%」；缺失显示「—」。 */
export function formatRankPercent(rank: number | null | undefined): string {
  if (isMissing(rank)) return '—'
  return `${Math.round((rank as number) * 100)}%`
}

/** 较前 7 日增减：正数带 +、负数带 -；无对比数据返回文案（页面拼在「较前 7 日」后面）。 */
export function formatDelta(delta: number | null | undefined): string {
  if (isMissing(delta)) return '暂无对比（历史数据不足）'
  const v = delta as number
  return v > 0 ? `+${formatCount(v)}` : formatCount(v)
}

/** 增减颜色：涨绿跌红；无数据用弱化色。 */
export function deltaToneClass(delta: number | null | undefined): string {
  if (isMissing(delta)) return 'text-muted-foreground'
  const v = delta as number
  if (v > 0) return 'text-success'
  if (v < 0) return 'text-destructive'
  return 'text-muted-foreground'
}

// 后端时间是北京时区 naive ISO 字符串（如 2026-11-01T06:50:36.473059），
// 直接截取年月日时分，避免浏览器按本地时区换算导致「数据更新至」时间漂移。
const DATETIME_RE = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/

/** 数据更新时间：YYYY-MM-DD HH:mm；缺失显示「暂无数据」。 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return MISSING_TEXT
  const m = DATETIME_RE.exec(value)
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : MISSING_TEXT
}

/** 列表发布时间：MM-DD HH:mm；缺失显示「未记录」。 */
export function formatMonthDayTime(value: string | null | undefined): string {
  if (!value) return '未记录'
  const m = DATETIME_RE.exec(value)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : '未记录'
}

/** 图表横轴日期：YYYY-MM-DD → MM-DD。 */
export function formatMonthDay(value: string | null | undefined): string {
  if (!value) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
  return m ? `${m[2]}-${m[3]}` : value
}

const STATUS_TONE: Record<string, StatusTone> = {
  approved: 'success', // 通过
  private: 'secondary', // 私密（灰）
  rejected: 'destructive', // 不适宜公开（红）
  published: 'default', // 已发布（主题色/蓝）
  unknown: 'secondary' // 状态未知
}

/** 作品状态 → 徽标色调。 */
export function statusTone(status: string | null | undefined): StatusTone {
  return (status && STATUS_TONE[status]) || 'secondary'
}

/** 后台 unit → 展示值：ratio → 百分比；秒保留 1 位；其余拼中文单位（次/条/篇/人）。 */
export function formatUnitValue(value: number | null | undefined, unit: string | null | undefined): string {
  if (isMissing(value)) return MISSING_TEXT
  const v = value as number
  const u = unit || ''
  if (u === 'ratio') return formatPercent(v)
  if (u === '秒') return `${v.toFixed(1)}${u}`
  return `${formatCount(v)}${u}`
}
