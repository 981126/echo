import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { CalendarDays } from 'lucide-react'
import { apiJson } from '@/api/client'
import { buildTimelineModel, type VideoLike, type WorkLike } from '@/lib/timeline'
import { itemVariants } from '@/lib/motion'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

/** 发布轨迹时间线（R-193：从主页移到博主管理页顶部）；本地素材 + 云端作品。 */
export function TimelineCard() {
  const navigate = useNavigate()
  const videosQ = useQuery({
    queryKey: ['videos', 'timeline'],
    queryFn: () => apiJson<{ items: VideoLike[] }>('/api/videos?limit=500')
  })
  const worksQ = useQuery({
    queryKey: ['works', 'timeline'],
    queryFn: () => apiJson<{ items: WorkLike[] }>('/api/works')
  })
  const model = useMemo(
    () => buildTimelineModel(videosQ.data?.items ?? [], worksQ.data?.items ?? []),
    [videosQ.data, worksQ.data]
  )

  return (
    <motion.section variants={itemVariants}>
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <CalendarDays className="h-4 w-4 text-accent" />
          <CardTitle>时间线</CardTitle>
          <CardDescription>本地素材与云端作品的发布轨迹</CardDescription>
        </CardHeader>
        <CardContent>
          {videosQ.isLoading || worksQ.isLoading ? (
            <Skeleton className="h-28 w-full" />
          ) : !model.events.length ? (
            <div className="flex h-28 items-center justify-center text-sm text-muted-foreground">暂无视频时间记录</div>
          ) : (
            <div className="overflow-x-auto pb-2">
              <div className="relative h-32" style={{ width: model.width }}>
                <div className="absolute left-0 right-0 top-[52px] h-px bg-border" />
                {model.todayLeft !== null && (
                  <div className="absolute top-2 bottom-2 w-px bg-accent/60" style={{ left: model.todayLeft }}>
                    <span className="absolute -top-1 left-1 text-[10px] font-medium text-accent">今天</span>
                  </div>
                )}
                {model.months.map((m) => (
                  <span key={m.key} className="absolute top-0 text-[11px] text-muted-foreground" style={{ left: m.left }}>
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
                    {e.coverUrl ? (
                      <img
                        src={e.coverUrl}
                        alt=""
                        loading="lazy"
                        referrerPolicy="no-referrer"
                        className="h-12 w-12 rounded-md border border-border object-cover transition-transform duration-300 group-hover:scale-105"
                      />
                    ) : (
                      <span className="flex h-12 w-12 items-center justify-center rounded-md border border-border bg-muted text-[9px] font-semibold text-muted-foreground">
                        ECHO
                      </span>
                    )}
                    <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                    <span className="w-full truncate text-center text-[10px] text-muted-foreground">{e.title}</span>
                    {e.srcLabel && (
                      <span className="rounded-full bg-muted px-1.5 text-[9px] text-muted-foreground">{e.srcLabel}</span>
                    )}
                  </motion.button>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.section>
  )
}
