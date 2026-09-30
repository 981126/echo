// 展示格式化工具
export const PLATFORM_NAME: Record<string, string> = {
  douyin: '抖音',
  xiaohongshu: '小红书',
  bilibili: 'B站'
}

export function platformName(p?: string, fallback = ''): string {
  return (p && PLATFORM_NAME[p]) || p || fallback
}

export function fmtNum(n?: number | null): string {
  const v = Number(n || 0)
  if (v >= 10000) return `${(v / 10000).toFixed(v >= 100000 ? 0 : 1)}w`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

export function fmtDate(s?: string | null): string {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return String(s).slice(0, 10)
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** R-212：时分（自动保存时间戳「已自动保存 14:03」） */
export function fmtTime(t?: Date | string | null): string {
  if (!t) return ''
  const d = t instanceof Date ? t : new Date(t)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
