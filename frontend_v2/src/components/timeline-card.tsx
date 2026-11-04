import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { CalendarDays } from 'lucide-react'
import { apiJson } from '@/api/client'
import { CoverImage } from '@/components/ui/cover-image'
import { buildTimelineModel, type TlEvent, type VideoLike, type WorkLike } from '@/lib/timeline'
import { itemVariants, softIn } from '@/lib/motion'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

/** 移动端纵向时间线只渲染最近 N 条（与桌面共用同一份 model 数据） */
const MOBILE_LIMIT = 40
/** 同屏入场并发上限（R-218 §4.7.3：列表 ≤12，其余直接落定） */
const MOBILE_ANIMATED = 12

function monthLabel(date: string) {
  return `${date.slice(0, 4)}年${Number(date.slice(5, 7))}月`
}

/** 按月分组（events 已按日期倒序），并记录组内首条在整体列表中的序号（控制错峰动画数量） */
function groupByMonth(events: TlEvent[]) {
  const groups: { key: string; label: string; start: number; events: TlEvent[] }[] = []
  events.forEach((e, idx) => {
    const key = e.date.slice(0, 7)
    const last = groups[groups.length - 1]
    if (last && last.key === key) last.events.push(e)
    else groups.push({ key, label: monthLabel(e.date), start: idx, events: [e] })
  })
  return groups
}

/** 发布轨迹时间线（R-193：从主页移到博主管理页顶部）；本地素材 + 云端作品。 */
export function TimelineCard() {
  const navigate = useNavigate()
  const videosQ = useQuery({
    queryKey: ['videos', 'timeline'],
    queryFn: () => apiJson<{ items: VideoLike[] }>('/api/videos?limit=500')
  })
  const worksQ = useQuery({
    queryKey: ['works', 'timeline'],
    queryFn: () => apiJson<{ items: WorkLike[] }>('/api/works?slim=1')
  })
  const model = useMemo(
    () => buildTimelineModel(videosQ.data?.items ?? [], worksQ.data?.items ?? []),
    [videosQ.data, worksQ.data]
  )
  // R-218：<md 纵向时间线（按月分组，最近 40 条）；md+ 仍用下面的横向画布，同一份 model
  const mobileGroups = useMemo(() => groupByMonth(model.events.slice(0, MOBILE_LIMIT)), [model.events])

  return (
    <motion.section variants={itemVariants}>
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <CalendarDays className="h-4 w-4 shrink-0 text-accent" />
          <CardTitle>时间线</CardTitle>
          <CardDescription className="min-w-0">本地素材与云端作品的发布轨迹</CardDescription>
        </CardHeader>
        <CardContent>
          {videosQ.isLoading || worksQ.isLoading ? (
            <Skeleton className="h-28 w-full" />
          ) : !model.events.length ? (
            <div className="flex h-28 items-center justify-center text-sm text-muted-foreground">暂无视频时间记录</div>
          ) : (
            <>
              {/* 移动端：纵向时间线（无横向长条） */}
              <div className="md:hidden">
                <div className="space-y-4">
                  {mobileGroups.map((g) => (
                    <div key={g.key}>
                      <div className="mb-1.5 text-xs font-medium text-muted-foreground">{g.label}</div>
                      <ul className="space-y-2">
                        {g.events.map((e, i) => {
                          const order = g.start + i
                          return (
                            <motion.li
                              key={e.key}
                              initial={order < MOBILE_ANIMATED ? { opacity: 0.85, y: 8 } : false}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{ ...softIn, delay: Math.min(order, MOBILE_ANIMATED) * 0.03 }}
                            >
                              <button
                                onClick={() => navigate(e.kind === 'video' ? `/videos?edit=${e.id}` : '/videos')}
                                className="pressable flex min-h-11 w-full cursor-pointer items-center gap-2.5 rounded-lg border border-border bg-card px-2.5 py-2 text-left transition-colors active:bg-muted"
                              >
                                <CoverImage
                                  url={e.coverUrl}
                                  alt=""
                                  width={160}
                                  className="h-14 w-14 shrink-0 rounded-md border border-border object-cover"
                                  placeholder={
                                    <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-xs font-semibold text-muted-foreground">
                                      ECHO
                                    </span>
                                  }
                                />
                                <span className="min-w-0 flex-1">
                                  <span className="line-clamp-2 text-[13px] font-medium leading-snug">{e.fullTitle || e.title}</span>
                                  <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                                    <span className="tnum">{e.date}</span>
                                    <span>{e.srcLabel || (e.kind === 'video' ? '本地素材' : '云端作品')}</span>
                                    {e.status === 'planned' && <span className="rounded-full bg-muted px-1.5">计划发布</span>}
                                  </span>
                                </span>
                              </button>
                            </motion.li>
                          )
                        })}
                      </ul>
                    </div>
                  ))}
                </div>
                {model.events.length > MOBILE_LIMIT && (
                  <p className="mt-3 text-center text-xs text-muted-foreground">仅显示最近 {MOBILE_LIMIT} 条，更早内容请用电脑查看</p>
                )}
              </div>

              {/* 桌面 md+：保留原有横向时间线画布 */}
              <div className="hidden overflow-x-auto pb-2 md:block">
                <div className="relative h-32" style={{ width: model.width }}>
                  <div className="absolute left-0 right-0 top-[52px] h-px bg-border" />
                  {model.todayLeft !== null && (
                    <div className="absolute top-2 bottom-2 w-px bg-accent/60" style={{ left: model.todayLeft }}>
                      <span className="absolute -top-1 left-1 text-xs md:text-[10px] font-medium text-accent">今天</span>
                    </div>
                  )}
                  {model.months.map((m) => (
                    <span key={m.key} className="absolute top-0 text-xs md:text-[11px] text-muted-foreground" style={{ left: m.left }}>
                      {m.label}
                    </span>
                  ))}
                  {model.events.map((e, i) => (
                    <motion.button
                      key={e.key}
                      initial={{ opacity: 0, y: 14 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.04 * Math.min(i, 14), duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                      whileHover={{ y: -4 }}
                      onClick={() => navigate(e.kind === 'video' ? `/videos?edit=${e.id}` : '/videos')}
                      className="group absolute flex w-20 cursor-pointer flex-col items-center gap-1"
                      style={{ left: e.left - 40, top: 24 }}
                    >
                      <CoverImage
                        url={e.coverUrl}
                        alt=""
                        width={160}
                        className="h-12 w-12 rounded-md border border-border object-cover transition-transform duration-300 group-hover:scale-105"
                        placeholder={
                          <span className="flex h-12 w-12 items-center justify-center rounded-md border border-border bg-muted text-xs md:text-[9px] font-semibold text-muted-foreground">
                            ECHO
                          </span>
                        }
                      />
                      <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                      <span className="w-full truncate text-center text-xs md:text-[10px] text-muted-foreground">{e.title}</span>
                      {e.srcLabel && (
                        <span className="rounded-full bg-muted px-1.5 text-xs md:text-[9px] text-muted-foreground">{e.srcLabel}</span>
                      )}
                    </motion.button>
                  ))}
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </motion.section>
  )
}
