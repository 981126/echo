// 通用展示工具（R-061-C：跨页面复用，避免重复定义）
export const PLATFORM_NAMES = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
export const platformName = (p) => PLATFORM_NAMES[p] || p || ''

export function fmtNum(n) {
  n = Number(n || 0)
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return String(n)
}

export function fmt(v) {
  return v ? v.replace('T', ' ').slice(0, 16) : ''
}

export function parseTs(v) {
  if (!v) return null
  const d = new Date(String(v).replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? null : d.getTime()
}

export function tsLocal(ts) {
  if (!ts) return null
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function arrKey(arr) {
  return JSON.stringify([...(arr || [])].sort())
}
