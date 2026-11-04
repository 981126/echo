/**
 * 封面/头像缩略图 URL（R-243：从 pages/videos/types.ts 移到 lib/，全站页面共用）。
 *
 * 只对本地 `/covers/...` 生效：后端按显示宽度按需生成缩略图并落盘缓存（生成失败回退已预热
 * 的 w400，仍无则回退原图）；远端 CDN 图（如果以后有）原样返回，不硬套参数。
 * 原图直出时对标页 44 张要 ~4.25MB；160/400 缩略后同页 ~1MB 级。
 *
 * R-249 v2：URL 带缓存版本参数。缩略图响应 `Cache-Control: max-age=604800`，历史某次坏图
 * （截断/半张图）一旦被浏览器缓存，同一 URL 一周内会持续「裂图」且不会重新请求；改这个版本号
 * 即可让浏览器按新 URL 重新拉取。以后若再发现批量坏图缓存，递增此值即可。
 */
export const COVER_CACHE_VERSION = '20261105a'

export function coverThumb(url: string | null | undefined, w = 400): string {
  const u = url || ''
  if (!u.startsWith('/covers/')) return u
  return `${u}${u.includes('?') ? '&' : '?'}w=${w}&v=${COVER_CACHE_VERSION}`
}
