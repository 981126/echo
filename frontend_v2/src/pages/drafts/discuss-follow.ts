// R-206：讨论留痕「跟随最新」的判定（纯函数，便于单测）
import { isRunRow, type Discussion } from './types'

/** 距底部 ≤ 这个像素数就算「贴着最新」——太小会因行高取整误判，太大则翻历史时被抢滚动条 */
export const NEAR_BOTTOM_PX = 24

/**
 * 滚动容器是否贴着底部。
 *
 * 讨论留痕是「只往下长」的直播式列表：贴底时新内容要自动跟着来，作者向上翻看历史时**不能**
 * 抢滚动条（否则读到一半被拽走）。元素还没挂载（没切到讨论 tab）时按「贴底」处理。
 */
export function isNearBottom(
  el: { scrollTop: number; scrollHeight: number; clientHeight: number } | null | undefined
): boolean {
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX
}

/** 比 `lastSeenId` 更新的「真留痕」条数：`kind='run'` 是运行头（系统行），不算模型发言 */
export function countNewRows(rows: Discussion[], lastSeenId: number): number {
  return rows.filter((r) => r.id > lastSeenId && !isRunRow(r)).length
}

/** 留痕里的最大 id（运行头也算，用于推进「已看到哪条」的游标） */
export function maxRowId(rows: Discussion[]): number {
  return rows.reduce((max, r) => (r.id > max ? r.id : max), 0)
}
