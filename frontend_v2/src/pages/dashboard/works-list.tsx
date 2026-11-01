// R-244 数据看板右侧「近期作品」：可滚动列表 + 加载更多 + 选中高亮（替代原通知/活动管理）。
import { motion, useReducedMotion } from 'framer-motion'
import { Loader2, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { Thumb } from './charts'
import { formatCount, formatDateTime, formatMonthDayTime, statusTone } from './format'
import type { WorkItem } from './types'

export interface WorksListProps {
  items: WorkItem[]
  total: number
  dataTime: string | null
  selectedId: number | null
  onSelect: (postId: number) => void
  hasMore: boolean
  loading: boolean
  loadingMore: boolean
  onLoadMore: () => void
  onRefresh: () => void
  refreshing: boolean
  error: string | null
  onRetry: () => void
}

/** 列表里的指标：缺失显示 —（不是 0），真实 0 显示 0 */
function metricText(value: number | null): string {
  return value === null ? '—' : formatCount(value)
}

function WorksSkeleton() {
  return (
    <div className="space-y-2 p-3">
      {Array.from({ length: 5 }).map((_, index) => (
        <div key={index} className="flex gap-3">
          <Skeleton className="h-[72px] w-[54px] shrink-0" />
          <div className="min-w-0 flex-1 space-y-2 py-1">
            <Skeleton className="h-3.5 w-4/5" />
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        </div>
      ))}
    </div>
  )
}

export function WorksList({
  items,
  total,
  dataTime,
  selectedId,
  onSelect,
  hasMore,
  loading,
  loadingMore,
  onLoadMore,
  onRefresh,
  refreshing,
  error,
  onRetry
}: WorksListProps) {
  const reduce = useReducedMotion()
  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-[var(--shadow-card)] lg:h-full">
      <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <h2 className="text-sm font-semibold">近期作品</h2>
            {total > 0 ? <span className="text-[11px] text-muted-foreground">共 {total} 条</span> : null}
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">数据更新至：{formatDateTime(dataTime)}</p>
        </div>
        <Button variant="outline" size="sm" disabled={refreshing} onClick={onRefresh}>
          {refreshing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
          {refreshing ? '更新中…' : '更新数据'}
        </Button>
      </div>

      {error ? (
        <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-xs text-muted-foreground">
          <span>作品列表加载失败：{error}</span>
          <Button variant="outline" size="sm" onClick={onRetry}>重试</Button>
        </div>
      ) : loading ? (
        <WorksSkeleton />
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-4 py-12 text-center text-xs text-muted-foreground">
          <span>还没有同步到作品，点右上角「更新数据」</span>
        </div>
      ) : (
        <ScrollArea className="max-h-[420px] md:max-h-[520px] lg:max-h-none lg:min-h-0 lg:flex-1">
          <ul className="divide-y divide-border">
            {items.map((item, index) => {
              const selected = item.post_id === selectedId
              return (
                <li key={item.post_id}>
                  <motion.button
                    type="button"
                    onClick={() => onSelect(item.post_id)}
                    initial={reduce ? false : { opacity: 0.85 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.2, delay: reduce ? 0 : Math.min(index, 8) * 0.02 }}
                    className="relative flex w-full cursor-pointer gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted/60"
                    aria-pressed={selected}
                  >
                    {/* 选中态动画：整行淡入高亮 + 左侧竖条在行间平滑滑动 */}
                    <motion.span
                      aria-hidden
                      initial={false}
                      animate={{ opacity: selected ? 1 : 0 }}
                      transition={{ duration: 0.18 }}
                      className="pointer-events-none absolute inset-0 bg-accent-soft/50"
                    />
                    {selected ? (
                      <motion.span
                        aria-hidden
                        layoutId="works-selected-bar"
                        transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                        className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent"
                      />
                    ) : null}
                    <Thumb
                      url={item.cover_url}
                      alt={item.title || '作品封面'}
                      className="relative z-10 h-[72px] w-[54px] shrink-0 rounded-md border border-border"
                    />
                    <div className="relative z-10 min-w-0 flex-1">
                      <div className="flex items-start gap-2">
                        <p className="line-clamp-2 min-w-0 flex-1 text-xs font-medium leading-5" title={item.title}>{item.title || '无标题作品'}</p>
                        <Badge variant={statusTone(item.status)} className="shrink-0">{item.status_label || '—'}</Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">{formatMonthDayTime(item.publish_time)}</p>
                      <div className="tnum mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                        <span>播放 {metricText(item.plays)}</span>
                        <span>点赞 {metricText(item.likes)}</span>
                        <span>评论 {metricText(item.comments)}</span>
                        <span>分享 {metricText(item.shares)}</span>
                      </div>
                    </div>
                  </motion.button>
                </li>
              )
            })}
          </ul>
        </ScrollArea>
      )}

      {!loading && !error && hasMore ? (
        <div className="border-t border-border p-3">
          <Button variant="outline" size="sm" className="w-full" disabled={loadingMore} onClick={onLoadMore}>
            {loadingMore ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : null}
            {loadingMore ? '加载中…' : '加载更多'}
          </Button>
        </div>
      ) : null}
    </section>
  )
}
