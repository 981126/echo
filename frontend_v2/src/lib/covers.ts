/**
 * 封面/头像缩略图 URL（R-243：从 pages/videos/types.ts 移到 lib/，全站页面共用）。
 *
 * 只对本地 `/covers/...` 生效：后端按显示宽度按需生成缩略图并落盘缓存（生成失败回退已预热
 * 的 w400，仍无则回退原图）；远端 CDN 图（如果以后有）原样返回，不硬套参数。
 * 原图直出时对标页 44 张要 ~4.25MB；160/400 缩略后同页 ~1MB 级。
 */
export function coverThumb(url: string | null | undefined, w = 400): string {
  const u = url || ''
  if (!u.startsWith('/covers/')) return u
  return `${u}${u.includes('?') ? '&' : '?'}w=${w}`
}
